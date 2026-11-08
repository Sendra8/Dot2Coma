package io.github.sendra8.callbridge

import java.io.DataInputStream
import java.io.DataOutputStream

/**
 * Protocolo con el PC (igual que callbridge/bridge.py):
 *   trama = tipo (1 byte) | longitud (2 bytes, big-endian) | datos
 *   1 = audio PCM 16 bits little-endian, mono, 48 kHz, 10 ms
 *   2 = control JSON
 *   3 = ping
 * La conexión es a 127.0.0.1:PORT, que `adb reverse` lleva al PC por el cable USB.
 */
object Proto {
    const val RATE = 48000
    const val FRAME = 480
    const val PORT = 28200
    const val VERSION = 1
    const val T_AUDIO = 1
    const val T_CTRL = 2
    const val T_PING = 3

    fun write(out: DataOutputStream, type: Int, payload: ByteArray, len: Int = payload.size) {
        synchronized(out) {
            out.writeByte(type)
            out.writeShort(len)
            out.write(payload, 0, len)
            out.flush()
        }
    }

    class Frame(val type: Int, val data: ByteArray)

    fun read(input: DataInputStream): Frame {
        val type = input.readUnsignedByte()
        val len = input.readUnsignedShort()
        val data = ByteArray(len)
        input.readFully(data)
        return Frame(type, data)
    }

    /** int16 little-endian -> ShortArray */
    fun toShorts(b: ByteArray, out: ShortArray): Int {
        val n = minOf(b.size / 2, out.size)
        for (i in 0 until n) {
            out[i] = ((b[2 * i].toInt() and 0xff) or (b[2 * i + 1].toInt() shl 8)).toShort()
        }
        return n
    }

    /** ShortArray -> int16 little-endian */
    fun toBytes(s: ShortArray, n: Int, out: ByteArray) {
        for (i in 0 until n) {
            val v = s[i].toInt()
            out[2 * i] = (v and 0xff).toByte()
            out[2 * i + 1] = ((v shr 8) and 0xff).toByte()
        }
    }
}

/**
 * Búfer anti-jitter: silencio si se vacía, descarta lo antiguo si se acumula
 * (los relojes del PC y del móvil derivan ligeramente).
 */
class JitterBuffer(targetMs: Int = 60, maxMs: Int = 200) {
    private val target = Proto.RATE * targetMs / 1000
    private val max = Proto.RATE * maxMs / 1000
    private val buf = ShortArray(Proto.RATE)   // 1 s de capacidad
    private var head = 0
    private var size = 0
    private var primed = false

    @Synchronized
    fun write(src: ShortArray, n: Int) {
        for (i in 0 until n) {
            if (size == buf.size) { head = (head + 1) % buf.size; size-- }
            buf[(head + size) % buf.size] = src[i]
            size++
        }
        if (size > max) {              // demasiado retardo: quedarse con lo último
            val drop = size - target
            head = (head + drop) % buf.size
            size -= drop
        }
    }

    @Synchronized
    fun read(dst: ShortArray, n: Int) {
        if (!primed) {
            if (size < target) { dst.fill(0, 0, n); return }
            primed = true
        }
        if (size < n) {
            primed = false
            dst.fill(0, 0, n)
            return
        }
        for (i in 0 until n) dst[i] = buf[(head + i) % buf.size]
        head = (head + n) % buf.size
        size -= n
    }

    @Synchronized
    fun clear() { head = 0; size = 0; primed = false }

    @Synchronized
    fun millis(): Int = size * 1000 / Proto.RATE
}
