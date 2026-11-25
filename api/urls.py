from rest_framework.routers import DefaultRouter
from .views import WorkoutViewSet, BookingViewSet

router = DefaultRouter()
router.register("workouts", WorkoutViewSet, basename="workout")
router.register("bookings", BookingViewSet, basename="booking")

urlpatterns = router.urls
