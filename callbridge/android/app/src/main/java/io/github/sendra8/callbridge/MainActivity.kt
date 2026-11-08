package io.github.sendra8.callbridge

import android.Manifest
import android.app.Activity
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Color
import android.media.AudioManager
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.view.View
import android.view.WindowManager
import android.widget.Button
import android.widget.LinearLayout
import android.widget.ProgressBar
import android.widget.TextView

class MainActivity : Activity() {

    private lateinit var status: TextView
    private lateinit var detail: TextView
    private lateinit var recLabel: TextView
    private lateinit var connect: Button
    private lateinit var mute: Button
    private lateinit var record: Button
    private lateinit var routes: LinearLayout
    private lateinit var micBar: ProgressBar
    private lateinit var spkBar: ProgressBar
    private val ui = Handler(Looper.getMainLooper())
    private val listener: () -> Unit = { render() }
    private val ticker = object : Runnable {
        override fun run() { renderLevels(); ui.postDelayed(this, 100) }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)
        volumeControlStream = AudioManager.STREAM_VOICE_CALL   // botones de volumen = volumen de llamada
        status = findViewById(R.id.status)
        detail = findViewById(R.id.detail)
        recLabel = findViewById(R.id.rec_label)
        connect = findViewById(R.id.connect)
        mute = findViewById(R.id.mute)
        record = findViewById(R.id.record)
        routes = findViewById(R.id.routes)
        micBar = findViewById(R.id.mic_level)
        spkBar = findViewById(R.id.spk_level)

        connect.setOnClickListener {
            if (BridgeService.instance != null) {
                startService(Intent(this, BridgeService::class.java).setAction(BridgeService.ACTION_STOP))
            } else {
                requestPermsThenStart()
            }
        }
        mute.setOnClickListener { BridgeService.instance?.toggleMute() }
        record.setOnClickListener { BridgeService.instance?.toggleRecording() }
    }

    override fun onResume() {
        super.onResume()
        BridgeService.listeners.add(listener)
        ui.post(ticker)
        render()
    }

    override fun onPause() {
        BridgeService.listeners.remove(listener)
        ui.removeCallbacks(ticker)
        super.onPause()
    }

    private fun requestPermsThenStart() {
        val perms = mutableListOf(Manifest.permission.RECORD_AUDIO, Manifest.permission.BLUETOOTH_CONNECT)
        if (android.os.Build.VERSION.SDK_INT >= 33) perms += Manifest.permission.POST_NOTIFICATIONS
        val missing = perms.filter { checkSelfPermission(it) != PackageManager.PERMISSION_GRANTED }
        if (missing.isEmpty()) startBridge() else requestPermissions(missing.toTypedArray(), 1)
    }

    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<out String>, grantResults: IntArray) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (checkSelfPermission(Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED) {
            startBridge()
        } else {
            detail.text = "Sin permiso de micrófono no se puede usar el móvil como manos libres."
        }
    }

    private fun startBridge() {
        startForegroundService(Intent(this, BridgeService::class.java).setAction(BridgeService.ACTION_START))
        ui.postDelayed({ render() }, 300)
    }

    private fun render() {
        val s = BridgeService.instance
        val on = s != null
        connect.text = if (on) "Desconectar" else "Conectar"
        if (s == null) {
            status.text = "Desconectado"
            detail.text = "Conecta el móvil al portátil por USB, abre CallBridge en el PC y pulsa «Conectar»."
        } else {
            status.text = s.status
            detail.text = when {
                !s.connected -> "Comprueba el cable USB y que la depuración USB esté autorizada."
                s.pcAudioError.isNotBlank() -> "Audio del PC: ${s.pcAudioError}"
                else -> "En Teams: Altavoz «CABLE-A Input» y Micrófono «CABLE-B Output»."
            }
        }
        window.apply {
            if (s?.connected == true) addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
            else clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        }
        val live = s?.connected == true
        mute.isEnabled = live
        mute.text = if (s?.muted == true) "🎙 Activar micro" else "🔇 Silenciar"
        record.isEnabled = live
        record.text = if (s?.pcRecording == true) "■ Detener grabación" else "● Grabar llamada"
        recLabel.visibility = if (s?.pcRecording == true) View.VISIBLE else View.GONE
        recLabel.text = "● Grabando en el PC  " + fmt(s?.pcRecSeconds ?: 0)

        routes.removeAllViews()
        if (live) {
            val cur = s!!.currentRoute()
            for (r in s.routes()) {
                routes.addView(Button(this).apply {
                    text = if (r.label == cur) "✓ ${r.label}" else r.label
                    isAllCaps = false
                    alpha = if (r.label == cur) 1f else 0.7f
                    setOnClickListener { s.setRoute(r) }
                    layoutParams = LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f)
                })
            }
        }
        recLabel.setTextColor(Color.rgb(214, 59, 59))
    }

    private fun renderLevels() {
        val s = BridgeService.instance
        micBar.progress = ((s?.micLevel ?: 0f) * 140).toInt().coerceAtMost(100)
        spkBar.progress = ((s?.spkLevel ?: 0f) * 140).toInt().coerceAtMost(100)
        if (s?.pcRecording == true) recLabel.text = "● Grabando en el PC  " + fmt(s.pcRecSeconds)
    }

    private fun fmt(sec: Int) = "%02d:%02d".format(sec / 60, sec % 60)
}
