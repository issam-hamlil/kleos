package app.kleos.review.data

import android.content.SharedPreferences
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Log
import java.security.GeneralSecurityException
import java.security.KeyStore
import java.util.Base64
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

/** Reads and writes the server settings. An interface so view models can be tested. */
interface ConfigStore {
    fun load(): ServerConfig?

    fun save(config: ServerConfig)
}

/** Encrypts a secret for storage at rest. */
interface SecretCipher {
    fun encrypt(plain: String): String

    /** Null if the ciphertext is corrupt or the key is gone (e.g. app data restored elsewhere). */
    fun decrypt(stored: String): String?
}

/**
 * AES-256-GCM with a key held in the Android Keystore. The key never leaves
 * secure hardware (where available), so a copy of the preferences file alone
 * cannot recover the token.
 */
class KeystoreCipher(private val alias: String = "kleos_api_token") : SecretCipher {

    override fun encrypt(plain: String): String {
        val cipher = Cipher.getInstance(TRANSFORMATION)
        cipher.init(Cipher.ENCRYPT_MODE, key())
        val sealed = cipher.doFinal(plain.toByteArray(Charsets.UTF_8))
        return encoder.encodeToString(cipher.iv) + SEPARATOR + encoder.encodeToString(sealed)
    }

    override fun decrypt(stored: String): String? {
        val parts = stored.split(SEPARATOR)
        if (parts.size != 2) return null
        return try {
            val cipher = Cipher.getInstance(TRANSFORMATION)
            cipher.init(Cipher.DECRYPT_MODE, key(), GCMParameterSpec(TAG_BITS, decoder.decode(parts[0])))
            String(cipher.doFinal(decoder.decode(parts[1])), Charsets.UTF_8)
        } catch (error: GeneralSecurityException) {
            Log.w(TAG, "Stored token could not be decrypted; it must be entered again")
            null
        } catch (error: IllegalArgumentException) {
            Log.w(TAG, "Stored token is malformed; it must be entered again")
            null
        }
    }

    private fun key(): SecretKey {
        val keyStore = KeyStore.getInstance(KEYSTORE).apply { load(null) }
        (keyStore.getKey(alias, null) as? SecretKey)?.let { return it }
        val spec = KeyGenParameterSpec.Builder(
            alias,
            KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT,
        )
            .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
            .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
            .setKeySize(256)
            .build()
        return KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, KEYSTORE)
            .apply { init(spec) }
            .generateKey()
    }

    private companion object {
        const val TAG = "KeystoreCipher"
        const val KEYSTORE = "AndroidKeyStore"
        const val TRANSFORMATION = "AES/GCM/NoPadding"
        const val TAG_BITS = 128
        const val SEPARATOR = ":"
        val encoder: Base64.Encoder = Base64.getEncoder()
        val decoder: Base64.Decoder = Base64.getDecoder()
    }
}

/** Server settings plus the notifier's memory of which clips it already announced. */
class SettingsStore(
    private val prefs: SharedPreferences,
    private val cipher: SecretCipher,
) : ConfigStore {

    override fun load(): ServerConfig? {
        val url = prefs.getString(KEY_URL, null) ?: return null
        val sealed = prefs.getString(KEY_TOKEN, null) ?: return null
        val token = cipher.decrypt(sealed) ?: return null
        return ServerConfig(url, token)
    }

    override fun save(config: ServerConfig) {
        prefs.edit()
            .putString(KEY_URL, config.baseUrl)
            .putString(KEY_TOKEN, cipher.encrypt(config.token))
            .apply()
    }

    fun announcedClipIds(): Set<String> = prefs.getStringSet(KEY_ANNOUNCED, emptySet()).orEmpty().toSet()

    fun setAnnouncedClipIds(ids: Set<String>) {
        prefs.edit().putStringSet(KEY_ANNOUNCED, ids.toSet()).apply()
    }

    private companion object {
        const val KEY_URL = "server_url"
        const val KEY_TOKEN = "api_token_sealed"
        const val KEY_ANNOUNCED = "announced_clip_ids"
    }
}
