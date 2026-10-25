from django.urls import path, re_path
from core import views
from core.webhook import OfficialWebhook
from core.openapi import openapi_schema
from core.providers import Providers, UpstreamInterfaces, CopyToken, SyncConversations, ScopeCatalog

urlpatterns = [
    path('api/v1/openapi.json', openapi_schema),
    path('health/', views.Health.as_view()),
    path('webhooks/qq/<int:pk>/', OfficialWebhook.as_view()),
    path('api/v1/auth/<str:action>/', views.Auth.as_view()),
    path('api/v1/bots/', views.Bots.as_view()),
    path('api/v1/providers/', Providers.as_view()),
    path('api/v1/providers/<int:pk>/', Providers.as_view()),
    path('api/v1/upstream-interfaces/', UpstreamInterfaces.as_view()),
    path('api/v1/scopes/', ScopeCatalog.as_view()),
    path('api/v1/channels/<int:pk>/sync/', SyncConversations.as_view()),
    path('api/v1/bots/<int:pk>/', views.Bots.as_view()),
    path('api/v1/dashboard/overview/', views.DashboardOverview.as_view()),
    path('api/v1/users/', views.Users.as_view()),
    path('api/v1/quotas/', views.Quotas.as_view()),
    path('api/v1/users/<int:pk>/', views.UserLifecycle.as_view()),
    path('api/v1/invitations/', views.Invitations.as_view()),
    path('api/v1/invitations/accept/', views.AcceptInvitation.as_view()),
    path('api/v1/invitations/<int:pk>/revoke/', views.RevokeInvitation.as_view()),
    path('api/v1/events/', views.ManagementEvents.as_view()),
    path('api/v1/deliveries/', views.Deliveries.as_view()),
    path('api/v1/deliveries/<int:pk>/attempts/', views.DeliveryAttempts.as_view()),
    path('api/v1/deliveries/<int:pk>/replay/', views.ReplayDelivery.as_view()),
    path('api/v1/api-calls/', views.ApiCalls.as_view()),
    path('api/v1/grants/', views.Grants.as_view()),
    path('api/v1/my-grants/', views.MyGrants.as_view()),
    path('api/v1/subscriptions/', views.Subscriptions.as_view()),
    path('api/v1/keys/', views.Keys.as_view()),
    path('api/v1/keys/<int:pk>/', views.Keys.as_view()),
    path('api/v1/keys/<int:pk>/copy/', CopyToken.as_view()),
    path('api/v1/keys/<int:pk>/revoke/', views.RevokeKey.as_view()),
    path('api/v1/keys/<int:pk>/rotate/', views.RotateKey.as_view()),
    path('api/v1/owner/keys/<int:pk>/revoke/', views.RevokeKey.as_view(), {'global_revoke': True}),
    path('relay/v1/capabilities/', views.Capabilities.as_view()),
    path('relay/v1/events/', views.RelayEvents.as_view()),
    re_path(r'^(?:qq|onebot)/(?P<path>.*)$', views.Proxy.as_view()),
]
