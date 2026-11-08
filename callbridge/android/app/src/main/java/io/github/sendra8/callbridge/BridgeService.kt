package io.github.sendra8.callbridge

import android.annotation.SuppressLint
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.media.AudioAttributes
import android.media.AudioDeviceCallback
import android.media.AudioDeviceInfo
import android.media.AudioFormat
import android.media.AudioManager
import android.media.AudioRecord
import android.media.AudioTrack
import android.media.MediaRecorder
import android.media.audiofx.AcousticEchoCanceler
import android.media.audiofx.AutomaticGainControl
import android.media.audiofx.NoiseSuppressor
import android.os.Build
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import android.os.PowerManager
import org.json.JSONObject
import java.io.BufferedInputStream
import java.io.BufferedOutputStream
import java.io.DataInputStream
import java.io.DataOutputStream
import java.net.InetSocketAddress
import java.net.Socket
import java.util.concurrent.CopyOnWriteArrayList
import kotlin.math.abs
import kotlin.math.max

/**
 * Servicio en primer plano: mantiene la conexión con el PC y el audio de la llamada
 * aunque la pantalla esté apagada.
 */
class BridgeService : Service() {

    companion object {
        const val ACTION_START = "start"
        const val ACTION_STOP = "stop"
        const val ACTION_MUTE = "mute"
        private const val CHANNEL = "bridge"
        private const val NOTIF_ID = 1

        @Volatile var instance: BridgeService? = null
        val listeners = CopyOnWriteArrayList<() -> Unit>()
        private val main = Handler(Looper.getMainLooper())
        fun notifyUi() = main.post { listeners.forEach { it() } }
    }

    // ---------------------------------------------------------------- estado (UI)
    @Volatile var connected = false
    @Volatile var status = "Esperando al PC…"
    @Volatile var muted = false
    @Volatile var pcRecording = false
    @Volatile var pcRecSeconds = 0
    @Volatile var pcAudioError = ""
    @Volatile var micLevel = 0f
    @Volatile var spkLevel = 0f

    private lateinit var am: AudioManager
    private var wakeLock: PowerManager.WakeLock? = null
    @Volatile private var running = false
    @Volatile private var socket: Socket? = null
    @Volatile private var out: DataOutputStream? = null
    private val ring = JitterBuffer(60, 200)
    private var recordThread: Thread? = null
    private var playThread: Thread? = null
    @Volatile private var audioOn = false

    private val deviceCallback = object : AudioDeviceCallback() {
        override fun onAudioDevicesAdded(added: Array<out AudioDeviceInfo>) = onDevicesChanged(true)
        override fun onAudioDevicesRemoved(removed: Array<out AudioDeviceInfo>) = onDevicesChanged(false)
    }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onCreate() {
        super.onCreate()
        am = getSystemService(Context.AUDIO_SERVICE) as AudioManager
        instance = this
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            ACTION_STOP -> { stopSelf(); return START_NOT_STICKY }
            ACTION_MUTE -> { toggleMute(); return START_STICKY }
        }
        if (!running) {
            running = true
            startForeground(NOTIF_ID, buildNotification(), ServiceInfo.FOREGROUND_SERVICE_TYPE_MICROPHONE)
            wakeLock = (getSystemService(Context.POWER_SERVICE) as PowerManager)
                .newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "CallBridge:bridge").apply { acquire() }
            am.registerAudioDeviceCallback(deviceCallback, main)
            Thread(::netLoop, "net").start()
        }
        return START_STICKY
    }

    override fun onDestroy() {
        running = false
        closeSocket()
        stopAudio()
        am.unregisterAudioDeviceCallback(deviceCallback)
        wakeLock?.let { if (it.isHeld) it.release() }
        instance = null
        connected = false
        status = "Desconectado"
        notifyUi()
        super.onDestroy()
    }

    // ------------------------------------------------------------------- red
    private fun netLoop() {
        while (running) {
            try {
                val s = Socket()
                s.tcpNoDelay = true
                s.connect(InetSocketAddress("127.0.0.1", Proto.PORT), 1500)
                s.soTimeout = 5000
                socket = s
                session(s)
            } catch (e: Exception) {
                // El PC no está escuchando todavía: reintentar
            } finally {
                closeSocket()
                stopAudio()
                if (connected) { connected = false }
                status = "Esperando al PC… (cable USB + CallBridge abierto en el PC)"
                pcRecording = false
                updateNotification()
                notifyUi()
            }
            if (running) Thread.sleep(1000)
        }
    }

    private fun session(s: Socket) {
        val input = DataInputStream(BufferedInputStream(s.getInputStream()))
        val o = DataOutputStream(BufferedOutputStream(s.getOutputStream()))
        out = o
        sendCtrl(JSONObject().put("t", "hello").put("v", Proto.VERSION)
            .put("model", "${Build.MANUFACTURER} ${Build.MODEL}").put("rate", Proto.RATE))
        val shorts = ShortArray(Proto.FRAME * 4)
        while (running) {
            val f = Proto.read(input)
            when (f.type) {
                Proto.T_AUDIO -> {
                    val n = Proto.toShorts(f.data, shorts)
                    ring.write(shorts, n)
                    spkLevel = max(peak(shorts, n), spkLevel * 0.85f)
                }
                Proto.T_CTRL -> onControl(JSONObject(String(f.data, Charsets.UTF_8)))
                Proto.T_PING -> Unit
            }
        }
    }

    private fun onControl(m: JSONObject) {
        when (m.optString("t")) {
            "hello" -> {
                connected = true
                status = "Conectado al PC"
                startAudio()
                updateNotification()
            }
            "state" -> {
                pcRecording = m.optBoolean("rec")
                pcRecSeconds = m.optInt("rec_s")
                pcAudioError = m.optString("audio_error")
                updateNotification()
            }
        }
        notifyUi()
    }

    fun sendCtrl(j: JSONObject) {
        val o = out ?: return
        Thread {
            try { Proto.write(o, Proto.T_CTRL, j.toString().toByteArray(Charsets.UTF_8)) } catch (_: Exception) {}
        }.start()
    }

    private fun closeSocket() {
        try { socket?.close() } catch (_: Exception) {}
        socket = null
        out = null
    }

    // ----------------------------------------------------------------- audio
    @SuppressLint("MissingPermission") // se pide RECORD_AUDIO antes de arrancar el servicio
    private fun startAudio() {
        if (audioOn) return
        audioOn = true
        ring.clear()
        am.mode = AudioManager.MODE_IN_COMMUNICATION
        Routes.preferred(am)?.let { am.setCommunicationDevice(it.device) }

        recordThread = Thread({
            val minBuf = AudioRecord.getMinBufferSize(Proto.RATE, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT)
            // VOICE_COMMUNICATION activa el procesado de llamada del móvil (cancelación de eco incluida)
            val rec = AudioRecord(MediaRecorder.AudioSource.VOICE_COMMUNICATION, Proto.RATE,
                AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT, max(minBuf, Proto.FRAME * 2 * 4))
            val fx = listOfNotNull(
                if (AcousticEchoCanceler.isAvailable()) AcousticEchoCanceler.create(rec.audioSessionId) else null,
                if (NoiseSuppressor.isAvailable()) NoiseSuppressor.create(rec.audioSessionId) else null,
                if (AutomaticGainControl.isAvailable()) AutomaticGainControl.create(rec.audioSessionId) else null,
            )
            fx.forEach { it.enabled = true }
            val buf = ShortArray(Proto.FRAME)
            val bytes = ByteArray(Proto.FRAME * 2)
            try {
                rec.startRecording()
                while (audioOn) {
                    var got = 0
                    while (got < Proto.FRAME && audioOn) {
                        val r = rec.read(buf, got, Proto.FRAME - got)
                        if (r <= 0) break
                        got += r
                    }
                    if (got < Proto.FRAME) continue
                    if (muted) buf.fill(0)
                    micLevel = max(peak(buf, Proto.FRAME), micLevel * 0.85f)
                    Proto.toBytes(buf, Proto.FRAME, bytes)
                    val o = out ?: continue
                    try { Proto.write(o, Proto.T_AUDIO, bytes) } catch (_: Exception) { closeSocket() }
                }
            } finally {
                try { rec.stop() } catch (_: Exception) {}
                fx.forEach { it.release() }
                rec.release()
            }
        }, "mic").apply { priority = Thread.MAX_PRIORITY; start() }

        playThread = Thread({
            val minBuf = AudioTrack.getMinBufferSize(Proto.RATE, AudioFormat.CHANNEL_OUT_MONO, AudioFormat.ENCODING_PCM_16BIT)
            val track = AudioTrack.Builder()
                .setAudioAttributes(AudioAttributes.Builder()
                    .setUsage(AudioAttributes.USAGE_VOICE_COMMUNICATION)
                    .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH).build())
                .setAudioFormat(AudioFormat.Builder().setSampleRate(Proto.RATE)
                    .setChannelMask(AudioFormat.CHANNEL_OUT_MONO)
                    .setEncoding(AudioFormat.ENCODING_PCM_16BIT).build())
                .setBufferSizeInBytes(max(minBuf, Proto.FRAME * 2 * 4))
                .setTransferMode(AudioTrack.MODE_STREAM)
                .setPerformanceMode(AudioTrack.PERFORMANCE_MODE_LOW_LATENCY)
                .build()
            val buf = ShortArray(Proto.FRAME)
            try {
                track.play()
                while (audioOn) {
                    ring.read(buf, Proto.FRAME)
                    track.write(buf, 0, Proto.FRAME)   // bloquea: marca el ritmo de reproducción
                }
            } finally {
                try { track.stop() } catch (_: Exception) {}
                track.release()
            }
        }, "speaker").apply { priority = Thread.MAX_PRIORITY; start() }
        sendState()
    }

    private fun stopAudio() {
        if (!audioOn) return
        audioOn = false
        recordThread?.join(1000)
        playThread?.join(1000)
        recordThread = null
        playThread = null
        am.clearCommunicationDevice()
        am.mode = AudioManager.MODE_NORMAL
        micLevel = 0f
        spkLevel = 0f
    }

    private fun onDevicesChanged(added: Boolean) {
        // Al conectar unos cascos/Bluetooth, pasar a ellos (como en una llamada normal)
        if (audioOn && added) Routes.preferred(am)?.let { am.setCommunicationDevice(it.device) }
        sendState()
        notifyUi()
    }

    // ------------------------------------------------------------- acciones UI
    fun routes(): List<Route> = Routes.available(am)
    fun currentRoute(): String? = if (audioOn) Routes.current(am) else null

    fun setRoute(r: Route) {
        if (!audioOn) return
        am.setCommunicationDevice(r.device)
        sendState()
        notifyUi()
    }

    fun toggleMute() {
        muted = !muted
        sendState()
        updateNotification()
        notifyUi()
    }

    fun toggleRecording() = sendCtrl(JSONObject().put("t", "rec").put("on", !pcRecording))

    private fun sendState() = sendCtrl(JSONObject().put("t", "state").put("muted", muted)
        .put("route", Routes.current(am) ?: ""))

    // ---------------------------------------------------------- notificación
    private fun buildNotification(): Notification {
        val nm = getSystemService(NotificationManager::class.java)
        nm.createNotificationChannel(NotificationChannel(CHANNEL, "Puente con el PC", NotificationManager.IMPORTANCE_LOW))
        val open = PendingIntent.getActivity(this, 0, Intent(this, MainActivity::class.java), PendingIntent.FLAG_IMMUTABLE)
        fun action(a: String, req: Int) = PendingIntent.getService(this, req,
            Intent(this, BridgeService::class.java).setAction(a), PendingIntent.FLAG_IMMUTABLE)
        val text = buildString {
            append(status)
            if (pcRecording) append(" · ● Grabando")
            if (muted) append(" · Micro silenciado")
        }
        return Notification.Builder(this, CHANNEL)
            .setSmallIcon(R.drawable.ic_stat)
            .setContentTitle("CallBridge")
            .setContentText(text)
            .setContentIntent(open)
            .setOngoing(true)
            .addAction(Notification.Action.Builder(null, if (muted) "Activar micro" else "Silenciar", action(ACTION_MUTE, 1)).build())
            .addAction(Notification.Action.Builder(null, "Desconectar", action(ACTION_STOP, 2)).build())
            .build()
    }

    private fun updateNotification() {
        if (running) getSystemService(NotificationManager::class.java).notify(NOTIF_ID, buildNotification())
    }

    private fun peak(b: ShortArray, n: Int): Float {
        var m = 0
        for (i in 0 until n) m = max(m, abs(b[i].toInt()))
        return m / 32768f
    }
}
