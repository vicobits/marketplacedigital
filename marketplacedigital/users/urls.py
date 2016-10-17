from django.conf.urls import url
from . import views, forms


urlpatterns = [
    url(r'cadastro/$', views.register, name='register'),
    url(r'login/$', views.user_login, name='user_login'),
]
