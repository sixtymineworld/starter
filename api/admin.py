from django.contrib import admin
from .models import Booking, Workout

@admin.register(Workout)
class WorkoutAdmin(admin.ModelAdmin):
    list_display = ("id", "title", "available")
    search_fields = ("title",)
    list_editable = ("available",)


@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    list_display = ("id", "workout", "owner", "quantity", "status")
    list_filter = ("status", "workout")
    search_fields = ("workout__title", "owner__username")
    readonly_fields = ("owner",)