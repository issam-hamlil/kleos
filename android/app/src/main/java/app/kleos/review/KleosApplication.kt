package app.kleos.review

import android.app.Application
import android.content.Context
import app.kleos.review.data.ApiProvider
import app.kleos.review.data.HttpKleosApi
import app.kleos.review.data.KeystoreCipher
import app.kleos.review.data.KleosApi
import app.kleos.review.data.ServerConfig
import app.kleos.review.data.SettingsStore
import app.kleos.review.notify.ClipNotifier
import app.kleos.review.notify.PendingCheckWorker
import okhttp3.OkHttpClient
import java.util.concurrent.TimeUnit

/** Hand-rolled dependency container. The app is small enough not to need a DI framework. */
class AppContainer(context: Context) : ApiProvider {

    val settings = SettingsStore(
        context.getSharedPreferences("kleos_settings", Context.MODE_PRIVATE),
        KeystoreCipher(),
    )

    /**
     * Approving a clip can take minutes: Instagram transcodes before it will
     * publish. The read timeout is sized for that, not for ordinary reads.
     */
    private val client = OkHttpClient.Builder()
        .connectTimeout(15, TimeUnit.SECONDS)
        .readTimeout(11, TimeUnit.MINUTES)
        .build()

    @Volatile
    private var cached: Pair<ServerConfig, KleosApi>? = null

    fun apiFor(config: ServerConfig): KleosApi = HttpKleosApi(config, client)

    override fun api(): KleosApi? {
        val config = settings.load() ?: return null
        cached?.let { (savedConfig, api) -> if (savedConfig == config) return api }
        return apiFor(config).also { cached = config to it }
    }
}

class KleosApplication : Application() {
    lateinit var container: AppContainer
        private set

    override fun onCreate() {
        super.onCreate()
        container = AppContainer(this)
        ClipNotifier.ensureChannel(this)
        PendingCheckWorker.schedule(this)
    }
}
