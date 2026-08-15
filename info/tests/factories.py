"""Small helpers for building the object graph the tests need.

The models are heavily interconnected (a Student needs a Class, which needs a
Dept; an Assign needs all three plus a Course and a Teacher), so building one
by hand in every test is noisy. These keep the tests about behaviour.
"""
from django.contrib.auth import get_user_model

from info.models import (Assign, Class, Course, Dept, Student, Teacher)

User = get_user_model()


def make_dept(id='CS', name='Computer Science'):
    return Dept.objects.create(id=id, name=name)


def make_course(dept, id='CS101', name='Data Structures', shortname='DS'):
    return Course.objects.create(dept=dept, id=id, name=name, shortname=shortname)


def make_class(dept, id='CS-3A', section='A', sem=3):
    return Class.objects.create(id=id, dept=dept, section=section, sem=sem)


def make_student(class_id, usn='1CS20CS001', name='Test Student',
                 username=None, password='pass12345'):
    user = User.objects.create_user(username=username or usn.lower(), password=password)
    return Student.objects.create(user=user, class_id=class_id, USN=usn, name=name,
                                  sex='Male', DOB='2000-01-01')


def make_teacher(dept, id='T001', name='Test Teacher',
                 username=None, password='pass12345'):
    user = User.objects.create_user(username=username or id.lower(), password=password)
    return Teacher.objects.create(user=user, id=id, dept=dept, name=name,
                                  sex='Male', DOB='1980-01-01')


def make_assign(class_id, course, teacher):
    return Assign.objects.create(class_id=class_id, course=course, teacher=teacher)


def make_admin(username='admin', password='pass12345'):
    return User.objects.create_superuser(username=username, password=password,
                                         email='admin@example.com')
