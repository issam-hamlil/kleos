package app.kleos.review.ui

import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Insights
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material.icons.filled.VideoLibrary
import androidx.compose.material3.Icon
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.navigation.NavGraph.Companion.findStartDestination
import androidx.navigation.NavHostController
import androidx.navigation.NavType
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.currentBackStackEntryAsState
import androidx.navigation.compose.rememberNavController
import androidx.navigation.navArgument
import app.kleos.review.AppContainer
import app.kleos.review.ui.analytics.AnalyticsScreen
import app.kleos.review.ui.analytics.AnalyticsViewModel
import app.kleos.review.ui.queue.QueueScreen
import app.kleos.review.ui.queue.QueueViewModel
import app.kleos.review.ui.review.ReviewScreen
import app.kleos.review.ui.review.ReviewViewModel
import app.kleos.review.ui.settings.SettingsScreen
import app.kleos.review.ui.settings.SettingsViewModel

private enum class Tab(val route: String, val label: String, val icon: ImageVector) {
    QUEUE("queue", "Queue", Icons.Filled.VideoLibrary),
    ANALYTICS("analytics", "Analytics", Icons.Filled.Insights),
    SETTINGS("settings", "Settings", Icons.Filled.Settings),
}

private const val REVIEW_ROUTE = "review/{videoId}"

@Composable
fun KleosNavHost(container: AppContainer) {
    val nav = rememberNavController()
    val current by nav.currentBackStackEntryAsState()
    val route = current?.destination?.route
    val openSettings = { nav.openTab(Tab.SETTINGS) }

    Scaffold(
        bottomBar = {
            if (route != REVIEW_ROUTE) {
                NavigationBar {
                    Tab.entries.forEach { tab ->
                        NavigationBarItem(
                            selected = route == tab.route,
                            onClick = { nav.openTab(tab) },
                            icon = { Icon(tab.icon, contentDescription = null) },
                            label = { Text(tab.label) },
                        )
                    }
                }
            }
        },
    ) { padding ->
        NavHost(nav, startDestination = Tab.QUEUE.route, modifier = Modifier.padding(padding)) {
            composable(Tab.QUEUE.route) {
                QueueScreen(
                    viewModel = viewModel { QueueViewModel(container) },
                    onOpenClip = { videoId -> nav.navigate("review/$videoId") },
                    onOpenSettings = openSettings,
                )
            }
            composable(Tab.ANALYTICS.route) {
                AnalyticsScreen(viewModel = viewModel { AnalyticsViewModel(container) }, onOpenSettings = openSettings)
            }
            composable(Tab.SETTINGS.route) {
                SettingsScreen(viewModel = viewModel { SettingsViewModel(container.settings, container::apiFor) })
            }
            composable(REVIEW_ROUTE, arguments = listOf(navArgument("videoId") { type = NavType.StringType })) { entry ->
                val videoId = entry.arguments?.getString("videoId").orEmpty()
                ReviewScreen(
                    viewModel = viewModel(key = videoId) { ReviewViewModel(container, videoId) },
                    onBack = { nav.popBackStack() },
                    onOpenSettings = openSettings,
                )
            }
        }
    }
}

/** Standard bottom-nav behaviour: one copy of each tab, state kept when switching. */
private fun NavHostController.openTab(tab: Tab) {
    navigate(tab.route) {
        popUpTo(graph.findStartDestination().id) { saveState = true }
        launchSingleTop = true
        restoreState = true
    }
}
