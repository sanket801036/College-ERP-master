from django.urls import include, path
from drf_spectacular.views import (
                                   SpectacularAPIView,
                                   SpectacularRedocView,
                                   SpectacularSwaggerView,
)

import apis.views as api_view

endpoints = [
    path('details/', api_view.DetailView.as_view(), name='api-details'),
    path('attendance/', api_view.AttendanceView.as_view(), name='api-attendance'),
    path('marks/', api_view.MarksView.as_view(), name='api-marks'),
    path('timetable/', api_view.TimetableView.as_view(), name='api-timetable'),
    path('classes/', api_view.TeacherClassesView.as_view(), name='api-classes'),
    path('classes/<int:assign_id>/students/',
         api_view.ClassStudentsView.as_view(), name='api-class-students'),
]

urlpatterns = [
    # Browsable documentation. Being able to show someone the API is not the
    # same as describing it.
    path('schema/', SpectacularAPIView.as_view(), name='api-schema'),
    path('docs/', SpectacularSwaggerView.as_view(url_name='api-schema'),
         name='api-docs'),
    path('redoc/', SpectacularRedocView.as_view(url_name='api-schema'),
         name='api-redoc'),

    # Versioned before anything consumes it - adding a prefix once clients exist
    # means breaking them. The unprefixed paths stay as aliases.
    path('v1/', include((endpoints, 'v1'), namespace='v1')),
]

urlpatterns += endpoints
