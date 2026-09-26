package app.kleos.review.data

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class ServerConfigValidatorTest {

    private fun validUrl(raw: String) = (ServerConfigValidator.url(raw) as Validation.Valid).value

    @Test
    fun `https addresses are accepted and normalised`() {
        assertEquals("https://kleos.example.com", validUrl("  https://kleos.example.com/  "))
    }

    @Test
    fun `a base path is kept`() {
        assertEquals("https://example.com/kleos", validUrl("https://example.com/kleos/"))
    }

    @Test
    fun `plain http to a public host is refused`() {
        val result = ServerConfigValidator.url("http://kleos.example.com")
        assertTrue(result is Validation.Invalid)
    }

    @Test
    fun `plain http to local development hosts is allowed`() {
        listOf("http://10.0.2.2:8000", "http://localhost:8000", "http://127.0.0.1:8000").forEach {
            assertTrue(it, ServerConfigValidator.url(it) is Validation.Valid)
        }
    }

    @Test
    fun `blank, malformed and query-carrying addresses are refused`() {
        listOf("", "   ", "kleos.example.com", "ftp://x.com", "https://x.com/?token=abc").forEach {
            assertTrue(it, ServerConfigValidator.url(it) is Validation.Invalid)
        }
    }

    @Test
    fun `tokens shorter than the server minimum are refused`() {
        assertTrue(ServerConfigValidator.token("a".repeat(23)) is Validation.Invalid)
        assertTrue(ServerConfigValidator.token("a".repeat(24)) is Validation.Valid)
    }

    @Test
    fun `tokens with inner whitespace are refused, surrounding whitespace is trimmed`() {
        assertTrue(ServerConfigValidator.token("abc def ghi jkl mno pqr stu") is Validation.Invalid)
        assertEquals("a".repeat(30), (ServerConfigValidator.token("  ${"a".repeat(30)}\n") as Validation.Valid).value)
    }
}
