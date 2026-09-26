package app.kleos.review.data

import okhttp3.HttpUrl.Companion.toHttpUrlOrNull

/** Where the Kleos server is and how to authenticate to it. */
data class ServerConfig(val baseUrl: String, val token: String) {
    /** Never print the token, even in a crash report or debugger string. */
    override fun toString(): String = "ServerConfig(baseUrl=$baseUrl, token=***)"
}

sealed interface Validation {
    data class Valid(val value: String) : Validation
    data class Invalid(val reason: String) : Validation
}

/**
 * Input checks for the settings screen.
 *
 * Plain HTTP is refused except for local development hosts. The token travels
 * in a header on every request, and over cleartext anyone on the network could
 * read it and approve clips to your accounts.
 */
object ServerConfigValidator {
    /** Must match the server's minimum; shorter tokens are refused there anyway. */
    const val MIN_TOKEN_LENGTH = 24

    private val DEV_HOSTS = setOf("localhost", "127.0.0.1", "10.0.2.2")

    fun url(raw: String): Validation {
        val trimmed = raw.trim().trimEnd('/')
        if (trimmed.isEmpty()) return Validation.Invalid("Enter the server address")
        val parsed = trimmed.toHttpUrlOrNull()
            ?: return Validation.Invalid("Not a valid http(s) address")
        if (parsed.scheme == "http" && parsed.host !in DEV_HOSTS) {
            return Validation.Invalid("Use https:// - plain http is only allowed for local testing")
        }
        if (parsed.query != null || parsed.fragment != null) {
            return Validation.Invalid("Remove the query string from the address")
        }
        return Validation.Valid(trimmed)
    }

    fun token(raw: String): Validation {
        val trimmed = raw.trim()
        return when {
            trimmed.length < MIN_TOKEN_LENGTH ->
                Validation.Invalid("Token must be at least $MIN_TOKEN_LENGTH characters")
            trimmed.any { it.isWhitespace() } -> Validation.Invalid("Token cannot contain spaces")
            else -> Validation.Valid(trimmed)
        }
    }
}
