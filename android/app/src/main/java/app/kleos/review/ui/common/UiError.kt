package app.kleos.review.ui.common

import app.kleos.review.data.ApiException
import java.io.IOException

/** A failure worded for the operator, plus whether fixing it means visiting Settings. */
data class UiError(val message: String, val needsSetup: Boolean = false)

val NotConfigured = UiError("Connect to your Kleos server in Settings first.", needsSetup = true)

fun Throwable.toUiError(): UiError = when {
    this is ApiException && isUnauthorized ->
        UiError("The server rejected the token. Check it in Settings.", needsSetup = true)
    this is ApiException && status == 503 ->
        UiError("The server's review API is off. Set KLEOS_API_TOKEN on the server.", needsSetup = true)
    this is ApiException && status == 409 ->
        UiError("This clip was already approved, rejected, or expired.")
    this is ApiException && status == 423 ->
        UiError("Publishing is paused by the server's kill switch.")
    this is ApiException && status == 404 ->
        UiError("This clip is no longer available.")
    this is ApiException -> UiError(message ?: "The server returned an error (${status}).")
    this is IOException -> UiError("Can't reach the server. Check the address and your connection.")
    else -> UiError("Something went wrong: ${message ?: javaClass.simpleName}")
}
