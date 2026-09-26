package app.kleos.review.ui.common

import app.kleos.review.data.ApiException
import app.kleos.review.notify.NewClipDetector
import app.kleos.review.testing.sampleClip
import java.io.IOException
import java.time.Instant
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class FormattingTest {

    private val now = Instant.parse("2026-09-26T12:00:00Z")

    @Test
    fun `durations render as minutes and seconds`() {
        assertEquals("1:32", Formatting.duration(92.0))
        assertEquals("0:07", Formatting.duration(6.6))
        assertEquals("0:00", Formatting.duration(-3.0))
    }

    @Test
    fun `expiry counts down in hours and minutes`() {
        assertEquals("Expires in 2h 30m", Formatting.expiresIn("2026-09-26T14:30:00+00:00", now))
        assertEquals("Expires in 5m", Formatting.expiresIn("2026-09-26T12:05:00+00:00", now))
        assertEquals("Expires in 1m", Formatting.expiresIn("2026-09-26T12:00:20+00:00", now))
    }

    @Test
    fun `past or unparseable expiry is reported plainly`() {
        assertEquals("Expiring now", Formatting.expiresIn("2026-09-26T11:00:00+00:00", now))
        assertEquals("Expiry unknown", Formatting.expiresIn("not a date", now))
    }

    @Test
    fun `python isoformat with microseconds parses`() {
        assertEquals("12m ago", Formatting.ago("2026-09-26T11:47:30.123456+00:00", now))
    }

    @Test
    fun `relative times cover minutes hours and days`() {
        assertEquals("Just now", Formatting.ago("2026-09-26T11:59:30+00:00", now))
        assertEquals("3h ago", Formatting.ago("2026-09-26T09:00:00+00:00", now))
        assertEquals("2d ago", Formatting.ago("2026-09-24T12:00:00+00:00", now))
    }

    @Test
    fun `percent and review time handle missing data`() {
        assertEquals("67%", Formatting.percent(2.0 / 3))
        assertEquals("-", Formatting.percent(null))
        assertEquals("45s", Formatting.reviewTime(0.75))
        assertEquals("12m", Formatting.reviewTime(12.4))
        assertEquals("2h 5m", Formatting.reviewTime(125.0))
        assertEquals("-", Formatting.reviewTime(null))
    }

    @Test
    fun `platform names are labelled for display`() {
        assertEquals("X", Formatting.platformLabel("x"))
        assertEquals("Instagram", Formatting.platformLabel("instagram"))
        assertEquals("Tiktok", Formatting.platformLabel("tiktok"))
    }

    @Test
    fun `errors map to actionable messages`() {
        assertTrue(ApiException(401, "x").toUiError().needsSetup)
        assertTrue(ApiException(503, "x").toUiError().needsSetup)
        assertFalse(ApiException(409, "x").toUiError().needsSetup)
        assertTrue(IOException("timeout").toUiError().message.contains("reach the server"))
        assertEquals("custom", ApiException(500, "custom").toUiError().message)
    }

    @Test
    fun `only clips not yet announced are new`() {
        val pending = listOf(sampleClip("a"), sampleClip("b"), sampleClip("c"))
        assertEquals(listOf("c"), NewClipDetector.newClips(pending, setOf("a", "b", "gone")).map { it.videoId })
        assertEquals(emptyList<String>(), NewClipDetector.newClips(emptyList(), setOf("a")).map { it.videoId })
    }
}
