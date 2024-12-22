from rest_framework import serializers

# Serializer to handle the image upload (image file)
class ImageMeasurementRequestSerializer(serializers.Serializer):
    images = serializers.ListField(child=serializers.ImageField())

# Response serializer remains the same as it is designed for structured data response
class ImageMeasurementResponseSerializer(serializers.Serializer):
    option = serializers.IntegerField()
    object = serializers.CharField()
    readings = serializers.DictField(child=serializers.CharField())
    accuracy = serializers.CharField()
    alert = serializers.CharField(required=False)
    recommendations = serializers.DictField(required=False, child=serializers.CharField())
    error = serializers.CharField(required=False)
