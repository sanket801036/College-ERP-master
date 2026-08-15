from django.contrib import admin
from django.urls import path, include
from django.contrib.auth import views as auth_views

from info.views import ErpLoginView, ErpPasswordChangeView, support_request

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('info.urls')),
    path('info/', include('info.urls')),
    path('api/', include('apis.urls')),
    path('accounts/login/', ErpLoginView.as_view(), name='login'),
    path('accounts/support/', support_request, name='support_request'),
    path('accounts/logout/',
         auth_views.LogoutView.as_view(template_name='info/logout.html'), name='logout'),
    # Nobody could change their own password before this - accounts kept the
    # one they were issued indefinitely.
    path('accounts/password_change/',
         ErpPasswordChangeView.as_view(), name='password_change'),
    path('accounts/password_change/done/',
         auth_views.PasswordChangeDoneView.as_view(
             template_name='info/password_change_done.html'),
         name='password_change_done'),
]
