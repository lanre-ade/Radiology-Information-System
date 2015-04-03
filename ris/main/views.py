from __future__ import unicode_literals

from django.views.generic.base import TemplateView
from django.views.generic.edit import UpdateView
from django.shortcuts import render, render_to_response
from django.template import RequestContext
import os
from django.conf import settings
from django.core.files.storage import FileSystemStorage
from django.contrib import messages
from django.contrib.messages.views import SuccessMessageMixin
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.decorators import login_required
from django.contrib.formtools.wizard.views import SessionWizardView
from django.http import HttpResponseRedirect, HttpResponse

from django.db.models import Q
from django_tables2 import RequestConfig
from PIL import Image, ImageOps
import base64
import cStringIO

from django.forms.models import model_to_dict

from main.forms import AuthUserForm, UserProfileForm, PersonForm, RadiologyRecordForm, CreateRadiologyRecordForm, UploadImageForm
from main.models import User, Person, RadiologyRecord, PacsImage, FamilyDoctor
from main.tables import RecordSearchTable, EditableRecordSearchTable
from main.utils import get_first

# Create your views here.

# adapted from http://www.tangowithdjango.com/book/chapters/login.html
def register(request):
    context = RequestContext(request)

    registered = False

    if request.method == 'POST':
        auth_user_form = AuthUserForm(data=request.POST)
        user_form = UserProfileForm(data=request.POST)
        person_form = PersonForm(data=request.POST)

        if  auth_user_form.is_valid() and person_form.is_valid() and user_form.is_valid():
            auth_user = auth_user_form.save()

            auth_user.set_password(auth_user.password)
            auth_user.save()

            person = Person.objects.create(**person_form.cleaned_data)
            class_field = user_form.cleaned_data['class_field']

            user = User.objects.create(
                auth_user=auth_user,
                person=person,
                password=auth_user.password,
                username=auth_user.username,
                class_field=class_field)

            registered = True

        else:
            print auth_user_form.errors, user_form.errors

    else:
        auth_user_form = AuthUserForm()
        person_form = PersonForm()
        user_form = UserProfileForm()

    return render_to_response(
            'main/registration.html',
            {'user_form': user_form, 'auth_user_form': auth_user_form, 'person_form': person_form, 'registered': registered},
            context)


def user_login(request):
    context = RequestContext(request)
    logged_in = request.user.is_authenticated()
    if logged_in:
        return HttpResponseRedirect('/ris/')

    if request.method == 'POST':
        auth_form = AuthenticationForm(data=request.POST)

        if auth_form.is_valid():
            user = auth_form.get_user()
            if user.is_active:
                login(request, user)
                return HttpResponseRedirect('/ris/')
            else:
                return HttpResponse("Your account is disabled.")
        else:
            print "Invalid login details"
            print auth_form.errors

    else:
        auth_form = AuthenticationForm()
    return render_to_response('main/login.html', {'auth_form':auth_form}, context)



@login_required
def user_logout(request):
    logout(request)

    return HttpResponseRedirect('/ris/')



class HomePageView(TemplateView):
    template_name = 'main/home.html'

    def get(self, *args, **kwargs):
        context = RequestContext(self.request)

        if not self.request.user.is_authenticated():
            return HttpResponseRedirect('/ris/login')

        try:
            user = User.objects.get(auth_user__id=self.request.user.id)
            person = user.person

            if user.class_field == 'r':
                query = RadiologyRecord.objects.all().filter(radiologist=person)
                table = EditableRecordSearchTable(self.build_table_data(query))
            elif user.class_field == 'd':
                query = RadiologyRecord.objects.all().filter(doctor=person)
                table = EditableRecordSearchTable(self.build_table_data(query))
            else:
                query = RadiologyRecord.objects.all().filter(patient=person)
                table = EditableRecordSearchTable(self.build_table_data(query))

        except Exception,e:
            print str(e)
            return HttpResponseRedirect('/ris/logout')
        RequestConfig(self.request).configure(table)
        return render(self.request,'main/home.html', {'table':table})

    def build_table_data(self, query):
        data = []
        for record in query:
            record_dict = model_to_dict(record)
            try:
                record_dict['thumbnail'] = get_first(record.pacsimage_set.all()).thumbnail
            except:
                pass
            data.append(record_dict)
        return data



@login_required
def create_radiology_record(request):
    context = RequestContext(request)

    # If it's a HTTP POST, we're interested in processing form data.
    if request.method == 'POST':
        form = CreateRadiologyRecordForm(request.POST, request.FILES)
        if  form.is_valid():

            patient = form.cleaned_data['patient']
            doctor = form.cleaned_data['doctor']
            radiologist = User.objects.get(auth_user__id=request.user.id).person
            image = form.cleaned_data.pop('image')
            radiology_record = RadiologyRecord.objects.create(
                radiologist=radiologist,
                **form.cleaned_data)

            # build base64 encoding for images
            if image:

                image = image.read()
                image_b64 = base64.b64encode(image)

                regular = ImageOps.fit(Image.open(cStringIO.StringIO(image)), (600,600), Image.ANTIALIAS)
                regular_buffer = cStringIO.StringIO()
                regular.save(regular_buffer, format="JPEG")
                regular_b64 = base64.b64encode(regular_buffer.getvalue())

                thumb = ImageOps.fit(Image.open(cStringIO.StringIO(image)), (200,200), Image.ANTIALIAS)
                thumb_buffer = cStringIO.StringIO()
                thumb.save(thumb_buffer, format="JPEG")
                thumb_b64 = base64.b64encode(thumb_buffer.getvalue())

                # add pacs image to database
                pacs_image = PacsImage.objects.create(
                    record=radiology_record,
                    full_size=image_b64,
                    regular_size=regular_b64,
                    thumbnail=thumb_b64
                )
            messages.success(request, "Radiology Record added successfully!")
            return HttpResponseRedirect('/ris/')


        else:
            print form.errors

    # Not a HTTP POST, so we render our form using two ModelForm instances.
    # These forms will be blank, ready for user input.
    else:
        form = CreateRadiologyRecordForm()


    # Render the template depending on the context.
    return render_to_response(
            'main/create_record.html',
            {'form': form},
            context)


class UpdateRadiologyRecordView(SuccessMessageMixin, UpdateView):
    template_name = 'main/update_record.html'
    form_class = RadiologyRecordForm
    model = RadiologyRecord
    lookup_url_kwarg = "record_id"
    success_url = '/ris/'
    success_message = "successfully updated"

    def get_object(self, queryset=None):
        print self.lookup_url_kwarg
        obj = RadiologyRecord.objects.get(record_id=self.kwargs.get(self.lookup_url_kwarg))
        return obj

    def form_valid(self, form):
        form.instance.user = self.request.user
        form.save()
        return super(UpdateRadiologyRecordView, self).form_valid(form)


class AddImageView(TemplateView):
    template_name = 'main/upload_images.html'
    form_class = UploadImageForm
    success_message = "successfully added"

    def get(self, *args, **kwargs):
        context = RequestContext(self.request)

        form = self.form_class
        return render_to_response(
                self.template_name,
                {'form': form},
                context)

    def post(self, *args, **kwargs):
        context = RequestContext(self.request)
        form = self.form_class(self.request.POST, self.request.FILES)
        if  form.is_valid():
            image = form.cleaned_data.pop('image')

            # build base64 encoding for images
            if image:
                image = image.read()
                image_b64 = base64.b64encode(image)

                regular = ImageOps.fit(Image.open(cStringIO.StringIO(image)), (600,600), Image.ANTIALIAS)
                regular_buffer = cStringIO.StringIO()
                regular.save(regular_buffer, format="JPEG")
                regular_b64 = base64.b64encode(regular_buffer.getvalue())

                thumb = ImageOps.fit(Image.open(cStringIO.StringIO(image)), (200,200), Image.ANTIALIAS)
                thumb_buffer = cStringIO.StringIO()
                thumb.save(thumb_buffer, format="JPEG")
                thumb_b64 = base64.b64encode(thumb_buffer.getvalue())

                record = RadiologyRecord.objects.get(
                    record_id=self.request.GET.get('record_id')
                )
                # add pacs image to database
                pacs_image = PacsImage.objects.create(
                    record=record,
                    full_size=image_b64,
                    regular_size=regular_b64,
                    thumbnail=thumb_b64
                )
            return HttpResponseRedirect('/ris/')


class ThumbnailImageView(TemplateView):
    template_name = 'main/view_thumbnails.html'
    lookup_url_kwarg = "record_id"

    def get(self, *args, **kwargs):
        context = RequestContext(self.request)
        pacs_images = PacsImage.objects.filter(record__record_id=self.kwargs.get(self.lookup_url_kwarg))
        album = []
        for img in pacs_images:
            album.append({
                'thumbnail': img.thumbnail,
                'regular': ('/ris/images/%s/regular' % img.image_id),
                'full': ('/ris/images/%s/full' % img.image_id)
            })
        return render_to_response(
                self.template_name,
                {'album': album, 'record_id':self.kwargs.get(self.lookup_url_kwarg)},
                context)


class RegularImageView(TemplateView):
    template_name = 'main/view_image.html'
    lookup_url_kwarg = "image_id"

    def get(self, *args, **kwargs):
        context = RequestContext(self.request)
        pacs_image = PacsImage.objects.get(image_id=self.kwargs.get(self.lookup_url_kwarg))

        if not pacs_image.regular_size:
            return HttpResponseRedirect('/ris/images/%s/full' % pacs_image.image_id)
        return render_to_response(
                self.template_name,
                {'image':{
                    'image':pacs_image.regular_size,
                    'full': ('/ris/images/%s/full' % pacs_image.image_id),
                    },
                 'record_id':pacs_image.record.record_id
                },
                context)


class FullImageView(RegularImageView):


    def get(self, *args, **kwargs):
        context = RequestContext(self.request)
        pacs_image = PacsImage.objects.get(image_id=self.kwargs.get(self.lookup_url_kwarg))

        return render_to_response(
                self.template_name,
                {'image':{
                    'image':pacs_image.full_size,
                    'full': '#'
                    },
                 'record_id':pacs_image.record.record_id
                },
                context)
