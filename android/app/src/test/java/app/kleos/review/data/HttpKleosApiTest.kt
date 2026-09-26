package app.kleos.review.data

import kotlinx.coroutines.test.runTest
import okhttp3.OkHttpClient
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Before
import org.junit.Test

class HttpKleosApiTest {

    private val server = MockWebServer()
    private lateinit var api: HttpKleosApi

    @Before
    fun setUp() {
        server.start()
        val base = server.url("/").toString().trimEnd('/')
        api = HttpKleosApi(ServerConfig(base, TOKEN), OkHttpClient())
    }

    @After
    fun tearDown() = server.shutdown()

    private fun respond(code: Int, body: String) {
        server.enqueue(MockResponse().setResponseCode(code).setBody(body))
    }

    @Test
    fun `every request carries the bearer token in a header`() = runTest {
        respond(200, """{"success":true,"data":[],"error":null}""")
        api.pending()
        val request = server.takeRequest()
        assertEquals("Bearer $TOKEN", request.getHeader("Authorization"))
        assertFalse("token must never appear in the URL", request.path!!.contains(TOKEN))
    }

    @Test
    fun `pending parses the envelope into clips`() = runTest {
        respond(
            200,
            """{"success":true,"error":null,"data":[{"video_id":"abc","title":"Goal","channel_id":"UC",
               "watch_url":"u","published_at":"p","created_at":"c","expires_at":"e","duration_s":61.5,
               "status":"pending","platforms":[],"future_field":"ignored"}]}""",
        )
        val clips = api.pending()
        assertEquals(listOf("abc"), clips.map { it.videoId })
        assertEquals(61.5, clips.single().durationS, 0.0)
        assertEquals("/api/pending", server.takeRequest().path)
    }

    @Test
    fun `approve posts the chosen platforms as json`() = runTest {
        respond(
            200,
            """{"success":true,"error":null,"data":{"video_id":"abc","results":[
               {"platform":"x","ok":false,"remote_id":"","error":"rate limited"}]}}""",
        )
        val response = api.approve("abc", listOf("x"))
        val request = server.takeRequest()
        assertEquals("POST", request.method)
        assertEquals("/api/clips/abc/approve", request.path)
        assertEquals("""{"platforms":["x"]}""", request.body.readUtf8())
        assertEquals("rate limited", response.results.single().error)
    }

    @Test
    fun `reject posts to the reject endpoint`() = runTest {
        respond(200, """{"success":true,"error":null,"data":{"video_id":"abc","status":"rejected"}}""")
        assertEquals("rejected", api.reject("abc").status)
        assertEquals("/api/clips/abc/reject", server.takeRequest().path)
    }

    @Test
    fun `a video id is always encoded as one path segment`() = runTest {
        respond(200, """{"success":true,"error":null,"data":{"video_id":"a","status":"rejected"}}""")
        api.reject("../../admin")
        assertTrue(server.takeRequest().path!!.startsWith("/api/clips/..%2F..%2Fadmin/reject"))
    }

    @Test
    fun `an error envelope becomes an ApiException with status and message`() = runTest {
        respond(409, """{"success":false,"data":null,"error":"clip is not pending"}""")
        try {
            api.reject("abc")
            fail("expected ApiException")
        } catch (error: ApiException) {
            assertEquals(409, error.status)
            assertEquals("clip is not pending", error.message)
        }
    }

    @Test
    fun `a 401 is recognisable as unauthorized`() = runTest {
        respond(401, """{"success":false,"data":null,"error":"invalid or missing token"}""")
        try {
            api.platforms()
            fail("expected ApiException")
        } catch (error: ApiException) {
            assertTrue(error.isUnauthorized)
        }
    }

    @Test
    fun `a non-json error page still produces a clear status`() = runTest {
        respond(502, "<html>Bad gateway</html>")
        try {
            api.analytics()
            fail("expected ApiException")
        } catch (error: ApiException) {
            assertEquals(502, error.status)
            assertEquals("HTTP 502", error.message)
        }
    }

    @Test
    fun `history sends the limit as a query parameter`() = runTest {
        respond(200, """{"success":true,"error":null,"data":[]}""")
        api.history(10)
        assertEquals("/api/history?limit=10", server.takeRequest().path)
    }

    @Test
    fun `stream url points at the clip and carries no secret`() {
        val url = api.streamUrl("abc")
        assertTrue(url.endsWith("/api/clips/abc/stream"))
        assertFalse(url.contains(TOKEN))
    }

    @Test
    fun `server config never prints its token`() {
        assertFalse(ServerConfig("https://x", TOKEN).toString().contains(TOKEN))
    }

    private companion object {
        const val TOKEN = "secret-token-abcdefghijklmnopqrstuvwxyz"
    }
}
