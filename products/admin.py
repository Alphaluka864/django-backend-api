

from django.contrib import admin
from .models import Category, Product


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "created_at")
    search_fields = ("name",)


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "name",
        "category",
        "price",
        "stock_quantity",
        "created_at",
    )
    search_fields = ("name", "description")
    list_filter = ("category", "created_at")
