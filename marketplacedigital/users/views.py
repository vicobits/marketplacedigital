from django.shortcuts import render, redirect, get_object_or_404
from django.conf import settings
from django.contrib.auth.models import User
from django.utils import timezone
from django.contrib.auth.decorators import login_required
from django.contrib.auth import authenticate, login, logout
from django.contrib import messages
from django.urls import reverse
from django.http import HttpResponse, HttpResponseRedirect
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt
from django.conf import settings
from django.db.models import Sum

# Imports for email sending
from django.core.mail import EmailMultiAlternatives
from django.template.loader import get_template
from django.template import Context

from .forms import RegistrationForm, LoginForm, ActivationLinkForm
from .models import Profile
from shop.models import Purchase, ProductFile
from marketplacedigital.settings.base import BASE_DIR
from marketplacedigital.settings import settings_secrets

from wsgiref.util import FileWrapper
import os, tempfile, zipfile
import hashlib
import random
import datetime
import requests
from sendfile import sendfile

def register(request):
    email_data = {}
    if request.user.is_authenticated():
        messages.info('Você já está logado, não precisa fazer um novo cadastro.')
        return redirect('/')
    if request.method == 'POST':
        form = RegistrationForm(request.POST)
        if form.is_valid():
            print('Form is valid')
            #datas['email_path']="/ActivationEmail.txt"
            email_data['email_subject']= "Ative sua conta - Marketplace Digital"
            # form.sendEmail(datas)


            user = User.objects.create_user(username=form.cleaned_data['username'],
                                            email=form.cleaned_data['email'],
                                            password=form.cleaned_data['password1'],
                                            first_name=form.cleaned_data['first_name'],
                                            last_name=form.cleaned_data['last_name']
                                            )

            user.save()

            # Generation of an activation key based on the username of the new user
            salt = hashlib.sha1(str(random.random()).encode('utf-8')).hexdigest()[:5]
            usernamesalt = user.username
            complete_salt = salt + usernamesalt
            complete_salt = complete_salt.encode('utf8')

            print(complete_salt)

            profile = Profile.objects.get(user=user)
            profile.activation_key = hashlib.sha1(complete_salt).hexdigest()
            profile.key_expiration = (datetime.datetime.strftime(datetime.datetime.now() +
                datetime.timedelta(days=7), "%Y-%m-%d %H:%M:%S"))
            profile.activated = False

            profile.save()

            send_activation_email(user, profile)

            messages.info(request, 'Um email com um link de ativação foi enviado para ' + user.email + '. Ative sua conta para fazer login.')

            return redirect('/')
    else:
        form = RegistrationForm() #Display form with error messages (incorrect fields, etc)
        print(form.errors)
    return render(request, 'users/register.html', locals())

def user_login(request):
    username = password = ''
    if request.method == 'POST':
        print('request POST')
        form = LoginForm(request.POST)
        if form.is_valid():
            print('form valido')
            username = form.cleaned_data['username']
            password = form.cleaned_data['password']

            user = authenticate(username=username, password=password)
            print(user)
            if user is not None:
                profile = Profile.objects.get(user=user)
                print(profile)
                if profile.activated:
                    login(request, user)
                    if request.POST.get('next'):
                        return redirect(request.POST.get('next'))
                    else:
                        return redirect('/')
                else:
                    form.add_error(None, 'Esta conta ainda não foi ativada. Caso não tenha recebido o email de ativação, clique no link abaixo.')
            else:
                form.add_error(None, 'Usuário e senha não conferem. Favor inserir uma combinação válida.')
        else:
            print('form invalido')
            print(form.errors)
    else:
        form = LoginForm()

    return render(request, 'users/login.html', { 'form' : form })

def user_logout(request):
    logout(request)
    return redirect('/')

#View called from activation email. Activate user if link didn't expire, or offer to
#send a second link if the first expired.
def activate(request, activation_key):
    activation_expired = False
    already_active = False
    profile = get_object_or_404(Profile, activation_key=activation_key)
    if profile.activated == False:
        if timezone.now() > profile.key_expiration:
            activation_expired = True #Display: offer the user to send a new activation link
            id_user = profile.user.id
        else: #Activation successful
            profile.activated = True
            profile.save()

    #If user is already active, simply display error message
    else:
        already_active = True #Display : error message
    return render(request, 'users/activation.html', locals())

@login_required(login_url='/usuario/login/')
def my_purchases(request):
    purchases = Purchase.objects.filter(user=request.user)
    return render(request, 'users/my_purchases.html', { 'purchases': purchases })

@login_required(login_url='/usuario/login/')
def my_sales(request):
    # my_products = Product.objects.filter(user=request.user)
    my_paid_sales = Purchase.objects.filter(product__user=request.user, paid=True)
    total_paid_sales_value = my_paid_sales.aggregate(Sum('value'))['value__sum']
    total_paid_sales_commission = my_paid_sales.aggregate(Sum('seller_commission'))['seller_commission__sum']

    my_non_paid_sales = Purchase.objects.filter(product__user=request.user, paid=False)
    total_non_paid_sales_value = my_non_paid_sales.aggregate(Sum('value'))['value__sum']
    total_non_paid_sales_commission = my_non_paid_sales.aggregate(Sum('seller_commission'))['seller_commission__sum']
    return render(request, 'users/my_sales.html', { 'my_paid_sales': my_paid_sales,
                                                    'my_non_paid_sales': my_non_paid_sales,
                                                    'total_paid_sales_value': total_paid_sales_value,
                                                    'total_paid_sales_commission': total_paid_sales_commission,
                                                    'total_non_paid_sales_value': total_non_paid_sales_value,
                                                    'total_non_paid_sales_commission': total_non_paid_sales_commission})

@login_required(login_url='/usuario/login/')
def show_purchase(request, purchase_id):
    purchase = get_object_or_404(Purchase, pk=purchase_id)
    if purchase.user != request.user:
        messages.warning(request, 'Você não tem permissão para acessar esta página.')
        return redirect('/')
    purchase_sample_files = ProductFile.objects.filter(product=purchase.product, sample_file=True)
    purchase_not_sample_files = ProductFile.objects.filter(product=purchase.product, sample_file=False)
    return render(request, 'users/show_purchase.html', { 'purchase': purchase, 'purchase_sample_files': purchase_sample_files,
                                                         'purchase_not_sample_files': purchase_not_sample_files })

@login_required(login_url='/usuario/login/')
def send_file(request, file_id):
    product_file = ProductFile.objects.get(id=file_id)
    purchase = Purchase.objects.filter(user=request.user).filter(product=product_file.product)
    if purchase:
        return sendfile(request, product_file.uploaded_file.name, attachment=True)
    else:
        messages.warning(request, 'Você não tem permissão para acessar este arquivo. Adquira-o primeiro.')
        return HttpResponseRedirect(reverse('show_product', args=(product_file.product.slug,)))

@csrf_exempt
def notificacao_pagseguro(request):
    if request.method == 'POST':
        request.encoding = 'ISO-8859-1'
        notification_code = request.POST['notificationCode']
        notification_type = request.POST['notificationType']

        dados_consulta = {
            "email": settings_secrets.PAGSEGURO_EMAIL,
            "token": settings_secrets.PAGSEGURO_TOKEN_SANDBOX
        }

        request_link = "https://ws.sandbox.pagseguro.uol.com.br/v3/transactions/notifications/" + notification_code

        r = requests.get(request_link, params=dados_consulta)
        r_texto = r.text

        purchase_id = find_between(r_texto, "<reference>","</reference>")
        transaction_status = find_between(r_texto, "<status>","</status>")

        purchase = Purchase.objects.get(pk=int(purchase_id))
        if transaction_status == "3":
            purchase.paid = True
            purchase.save()

            email_subject = "Linkplace - Olá " + user.first_name + ". Seu pagamento foi confirmado."
            from_email = "felipect86@gmail.com"
            to_email = user.email

            text_template = get_template('users/payment_confirmation.txt')
            html_template = get_template('users/payment_confirmation.html')

            d = Context({ 'purchase': purchase })

            text_content = text_template.render(d)
            html_content = html_template.render(d)

            msg = EmailMultiAlternatives(email_subject, text_content, from_email, [to_email])
            msg.attach_alternative(html_content, "text/html")
            msg.send()

        return HttpResponse('OK')
    else:
        return redirect('/')

def resend_activation_email(request):
    if request.method == 'POST':
        email = request.POST['email']
        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            user = None
        if user == None:
            messages.warning(request, 'Este email não está cadastrado. Caso queira, pode se cadastrar abaixo.')
            return HttpResponseRedirect(reverse('register'))

        profile = Profile.objects.get(user=user)
        if profile.activated:
            messages.info(request, 'Sua conta já está ativada e você já pode fazer login. Caso necessite, pode redefinir sua senha.')
            return HttpResponseRedirect(reverse('user_login'))

        profile.key_expiration = (datetime.datetime.strftime(datetime.datetime.now() +
            datetime.timedelta(days=7), "%Y-%m-%d %H:%M:%S"))
        profile.save()

        send_activation_email(user, profile)

        messages.info(request, 'O email com seu link de ativação foi reenviado para ' + user.email + '. Ative sua conta para fazer login.')

        return redirect('/')
    else:
        form = ActivationLinkForm()
        return render(request, 'users/resend_activation_email.html', { 'form' : form })


def find_between( s, first, last ):
    try:
        start = s.index( first ) + len( first )
        end = s.index( last, start )
        return s[start:end]
    except ValueError:
        return ""

def send_activation_email(user, profile):
    domain = settings.BASE_DOMAIN
    link = 'usuario/ativar/' + profile.activation_key
    activation_link = domain + link

    email_subject = "Olá " + user.first_name + ". Ative sua conta no Marketplace Digital"
    from_email = "felipect86@gmail.com"
    to_email = user.email

    text_template = get_template('users/activation_email.txt')
    html_template = get_template('users/activation_email.html')

    d = Context({ 'username': user.username, 'activation_link': activation_link, 'key_expiration': profile.key_expiration })

    text_content = text_template.render(d)
    html_content = html_template.render(d)

    msg = EmailMultiAlternatives(email_subject, text_content, from_email, [to_email])
    msg.attach_alternative(html_content, "text/html")
    msg.send()
