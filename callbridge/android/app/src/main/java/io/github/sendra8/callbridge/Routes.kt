package io.github.sendra8.callbridge

import android.media.AudioDeviceInfo
import android.media.AudioManager

/** Salidas de audio de "llamada" disponibles: altavoz, auricular, cascos, Bluetooth… */
data class Route(val label: String, val device: AudioDeviceInfo, val priority: Int)

object Routes {
    fun label(d: AudioDeviceInfo): Pair<String, Int>? = when (d.type) {
        AudioDeviceInfo.TYPE_BLUETOOTH_SCO, AudioDeviceInfo.TYPE_BLE_HEADSET ->
            "Bluetooth" + (d.productName?.toString()?.takeIf { it.isNotBlank() }?.let { " · $it" } ?: "") to 0
        AudioDeviceInfo.TYPE_WIRED_HEADSET, AudioDeviceInfo.TYPE_WIRED_HEADPHONES -> "Cascos" to 1
        AudioDeviceInfo.TYPE_USB_HEADSET -> "Cascos USB" to 1
        AudioDeviceInfo.TYPE_HEARING_AID -> "Audífono" to 1
        AudioDeviceInfo.TYPE_BUILTIN_SPEAKER -> "Altavoz" to 2
        AudioDeviceInfo.TYPE_BUILTIN_EARPIECE -> "Auricular" to 3
        else -> null
    }

    fun available(am: AudioManager): List<Route> {
        val seen = HashSet<String>()
        return am.availableCommunicationDevices.mapNotNull { d ->
            label(d)?.let { (l, p) -> if (seen.add(l)) Route(l, d, p) else null }
        }.sortedBy { it.priority }
    }

    /** Como en WhatsApp: si hay cascos/Bluetooth se usan; si no, manos libres (altavoz). */
    fun preferred(am: AudioManager): Route? = available(am).minByOrNull { it.priority }

    fun current(am: AudioManager): String? = am.communicationDevice?.let { label(it)?.first }
}
