from django.urls import include, path

from accounts.views2 import BankView, BarberFilter, ServicesView

from .register import DeleteUser, EmailView, LoginView, PasswordReset, RegistrationView
from .views import AuthenticateUser, BarberDetailsView, GetBarber, GetUser, UserDetailsView

urlpatterns = [
    path("", include("knox.urls")),
    path("register", RegistrationView.as_view()),
    path("login", LoginView.as_view()),
    path("verifyemail", EmailView.as_view()),
    path("passwordreset", PasswordReset.as_view()),
    path("userdetails", UserDetailsView.as_view()),
    path("barberdetails", BarberDetailsView.as_view()),
    path("deleteuser/<int:pk>", DeleteUser.as_view()),
    path("getbarber/<int:pk>", GetBarber.as_view()),
    path("getuser/<int:pk>", GetUser.as_view()),
    path("authenticateuser", AuthenticateUser.as_view()),
    path("createbank", BankView.as_view()),
    path("addservices", ServicesView.as_view()),
    path("filterbarbers", BarberFilter.as_view()),
]
