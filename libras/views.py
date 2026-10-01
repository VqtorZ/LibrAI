from django.http import JsonResponse, StreamingHttpResponse
from django.shortcuts import render
from .vision import camera


def home(request):
    return render(request, "libras/home.html")


def recognizer(request):
    return render(request, "libras/recognizer.html")


def video_feed(request):
    return StreamingHttpResponse(
        camera.frames(), content_type="multipart/x-mixed-replace; boundary=frame"
    )


def status(request):
    return JsonResponse(camera.status())
