from rest_framework.routers import DefaultRouter

router = DefaultRouter()
# router.register("bikes", BikeViewSet, basename="bike")
# router.register("rentals", RentalViewSet, basename="rental")

urlpatterns = router.urls
