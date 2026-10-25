from django.urls import path, re_path
from core import views
from core.webhook import OfficialWebhook

urlpatterns = [
    path('health/', views.Health.as_view()),
    path('webhooks/qq/<int:pk>/', OfficialWebhook.as_view()),
    path('api/v1/auth/<str:action>/', views.Auth.as_view()),
    path('api/v1/bots/', views.Bots.as_view()),
    path('api/v1/bots/<int:pk>/', views.Bots.as_view()),
    path('api/v1/dashboard/overview/', views.DashboardOverview.as_view()),
    path('api/v1/users/', views.Users.as_view()),
    path('api/v1/invitations/', views.Invitations.as_view()),
    path('api/v1/invitations/accept/', views.AcceptInvitation.as_view()),
    path('api/v1/events/', views.ManagementEvents.as_view()),
    path('api/v1/deliveries/', views.Deliveries.as_view()),
    path('api/v1/api-calls/', views.ApiCalls.as_view()),
    path('api/v1/grants/', views.Grants.as_view()),
    path('api/v1/my-grants/', views.MyGrants.as_view()),
    path('api/v1/subscriptions/', views.Subscriptions.as_view()),
    path('api/v1/keys/', views.Keys.as_view()),
    path('api/v1/keys/<int:pk>/revoke/', views.RevokeKey.as_view()),
    path('api/v1/keys/<int:pk>/rotate/', views.RotateKey.as_view()),
    path('api/v1/owner/keys/<int:pk>/revoke/', views.RevokeKey.as_view(), {'global_revoke': True}),
    path('relay/v1/capabilities/', views.Capabilities.as_view()),
    path('relay/v1/events/', views.RelayEvents.as_view()),
    re_path(r'^(?:qq|onebot)/(?P<path>.*)$', views.Proxy.as_view()),
]