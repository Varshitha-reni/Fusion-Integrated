from django.urls import path

from modules.elm.api import views

urlpatterns = [
    path(
        "applications",
        views.ApplicationListCreateView.as_view(),
        name="elm-applications",
    ),
    path(
        "applications/<int:pk>",
        views.ApplicationDetailView.as_view(),
        name="elm-application-detail",
    ),
    path(
        "applications/<int:pk>/withdraw",
        views.ApplicationWithdrawView.as_view(),
        name="elm-application-withdraw",
    ),
    path(
        "applications/<int:pk>/preflight",
        views.ApplicationPreflightView.as_view(),
        name="elm-application-preflight",
    ),
    path(
        "balances",
        views.LeaveBalanceListView.as_view(),
        name="elm-balances",
    ),
    path(
        "balances/history",
        views.LeaveBalanceHistoryView.as_view(),
        name="elm-balance-history",
    ),
]
