
from django_filters import rest_framework
from rest_framework import generics, permissions
from rest_framework.decorators import (
    api_view,
    permission_classes,
)
from rest_framework.response import Response

from .models import Product, ProductAuditLog, SellerProfile
from .serializers import ProductAuditLogSerializer
from .serializers import (
    ProductSerializer,
    UserRegistrationSerializer,
    SellerApplicationSerializer,
)
from .permissions import (
    IsAdminOrReadOnly,
    IsApprovedSellerOrAdmin,
)
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.filters import SearchFilter, OrderingFilter
from .models import InventoryMovement
from .serializers import InventoryMovementSerializer
from django.db.models import Count, DecimalField, F, Q, Sum
from rest_framework.permissions import IsAdminUser
from rest_framework.exceptions import ValidationError
from rest_framework import serializers
from .models import Category
from .serializers import CategorySerializer, SupplierSerializer
from .models import Supplier
from .models import PurchaseOrder, PurchaseOrderItem
from .serializers import PurchaseOrderSerializer
from django.utils import timezone
from rest_framework import status
from rest_framework.views import APIView
from django.db import transaction
from django.utils.dateparse import parse_date
from rest_framework.exceptions import ValidationError as DRFValidationError
from decimal import Decimal
from .throttles import RegistrationRateThrottle
from rest_framework.generics import ListAPIView
from .serializers import ProductAuditLogSerializer
from .serializers import SellerProfileAdminSerializer
from rest_framework.permissions import IsAuthenticated
from rest_framework.generics import ListAPIView, RetrieveAPIView
from rest_framework.views import APIView
from rest_framework.response import Response
from .serializers import (
    CustomerCheckoutSerializer,
    CustomerOrderSerializer,
    SellerOrderItemSerializer,
    SellerOrderStatusUpdateSerializer,
    CartSerializer,
    CartItemSerializer,
    CartItemWriteSerializer,
    CartItemUpdateSerializer,
)
from .models import CustomerOrder, CustomerOrderItem, Cart, CartItem, Product
from django.db import transaction
from drf_spectacular.utils import extend_schema, OpenApiTypes
from django.shortcuts import get_object_or_404

@extend_schema(
    responses={200: OpenApiTypes.OBJECT},
)
@api_view(["GET"])
@permission_classes([permissions.AllowAny])
def health_check(request):
    return Response({
        "status": "ok",
        "message": "Shop API is running",
    })




class ProductListCreateView(generics.ListCreateAPIView):
    serializer_class = ProductSerializer
    permission_classes = [IsApprovedSellerOrAdmin]

    filter_backends = [
        DjangoFilterBackend,
        SearchFilter,
        OrderingFilter,
    ]

    filterset_fields = ["category", "price", "status"]
    search_fields = ["name", "description", "category__name"]
    ordering_fields = [
        "name",
        "price",
        "created_at",
        "stock_quantity",
    ]
    ordering = ["id"]

    def get_queryset(self):
        user = self.request.user
        queryset = Product.objects.select_related(
            "category",
            "owner",
        )

        if user.is_authenticated and user.is_staff:
            return queryset.order_by("id")

        if (
            user.is_authenticated
            and hasattr(user, "seller_profile")
            and user.seller_profile.status == SellerProfile.Status.APPROVED
        ):
            if self.request.query_params.get("manage") == "true":
                queryset = queryset.filter(owner=user)
            else:
                queryset = queryset.filter(
                    status=Product.Status.PUBLISHED
                )

        else:
            queryset = queryset.filter(
                status=Product.Status.PUBLISHED
            )

        return queryset.order_by("id")

    def perform_create(self, serializer):
        user = self.request.user

        if user.is_staff:
            serializer.save()
            return

        serializer.save(
            owner=user,
            status=Product.Status.DRAFT,
        )


class ProductDetailView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = ProductSerializer
    permission_classes = [IsApprovedSellerOrAdmin]

    def get_queryset(self):
        user = self.request.user
        queryset = Product.objects.select_related(
            "category",
            "owner",
        )

        if user.is_authenticated and user.is_staff:
            return queryset

        if (
            user.is_authenticated
            and hasattr(user, "seller_profile")
            and user.seller_profile.status == SellerProfile.Status.APPROVED
        ):
            if self.request.method not in permissions.SAFE_METHODS:
                return queryset.filter(owner=user)

            if self.request.query_params.get("manage") == "true":
                return queryset.filter(owner=user)

            return queryset.filter(
                status=Product.Status.PUBLISHED
            )

        return queryset.filter(
            status=Product.Status.PUBLISHED
        )




class ProductWorkflowActionView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    transitions = {
        "submit-review": (
            Product.Status.DRAFT,
            Product.Status.UNDER_REVIEW,
            ProductAuditLog.Action.SUBMITTED,
        ),
        "approve": (
            Product.Status.UNDER_REVIEW,
            Product.Status.PUBLISHED,
            ProductAuditLog.Action.APPROVED,
        ),
        "return-to-draft": (
            Product.Status.UNDER_REVIEW,
            Product.Status.DRAFT,
            ProductAuditLog.Action.RETURNED,
        ),
    }
    @extend_schema(request=None, responses={200: OpenApiTypes.OBJECT})

    def post(self, request, pk, action):
        if action not in self.transitions:
            return Response(
                {"detail": "Unknown workflow action."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user = request.user

        # Only administrators can approve or return products.
        if action in {"approve", "return-to-draft"}:
            if not user.is_staff:
                return Response(
                    {"detail": "Administrator access required."},
                    status=status.HTTP_403_FORBIDDEN,
                )

        # Submission is available to administrators and approved
        # sellers, but sellers can submit only their own products.
        elif action == "submit-review":
            if not user.is_staff:
                try:
                    approved_seller = (
                        user.seller_profile.status
                        == SellerProfile.Status.APPROVED
                    )
                except SellerProfile.DoesNotExist:
                    approved_seller = False

                if not approved_seller:
                    return Response(
                        {
                            "detail": (
                                "Only approved sellers can submit "
                                "products for review."
                            )
                        },
                        status=status.HTTP_403_FORBIDDEN,
                    )

        expected_status, new_status, audit_action = (
            self.transitions[action]
        )

        with transaction.atomic():
            try:
                product = (
                    Product.objects
                    .select_for_update()
                    .get(pk=pk)
                )
            except Product.DoesNotExist:
                return Response(
                    {"detail": "Product not found."},
                    status=status.HTTP_404_NOT_FOUND,
                )

            # Sellers must own the product they submit.
            if (
                action == "submit-review"
                and not user.is_staff
                and product.owner_id != user.id
            ):
                return Response(
                    {
                        "detail": (
                            "You can submit only your own products."
                        )
                    },
                    status=status.HTTP_403_FORBIDDEN,
                )

            if product.status != expected_status:
                return Response(
                    {
                        "detail": (
                            f"Cannot perform '{action}' when product "
                            f"status is '{product.status}'."
                        ),
                        "current_status": product.status,
                        "required_status": expected_status,
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

            previous_status = product.status
            product.status = new_status
            product.save(update_fields=["status", "updated_at"])

            ProductAuditLog.objects.create(
                product=product,
                actor=user,
                action=audit_action,
                previous_status=previous_status,
                new_status=new_status,
            )

        return Response(
            {
                "id": product.id,
                "name": product.name,
                "status": product.status,
                "message": (
                    f"Product workflow action '{action}' completed."
                ),
            },
            status=status.HTTP_200_OK,
        )


class ProductReviewQueueView(ListAPIView):
    serializer_class = ProductSerializer
    permission_classes = [IsAdminUser]

    def get_queryset(self):
        return (
            Product.objects
            .filter(status=Product.Status.UNDER_REVIEW)
            .select_related("category")
            .order_by("created_at", "id")
        )


class ProductAuditLogListView(ListAPIView):
    serializer_class = ProductAuditLogSerializer
    permission_classes = [IsAdminUser]
    filter_backends = [DjangoFilterBackend, OrderingFilter]

    filterset_fields = ["product", "action"]
    ordering_fields = ["created_at", "id"]
    ordering = ["-created_at", "-id"]

    def get_queryset(self):
        return (
            ProductAuditLog.objects
            .select_related("product", "actor")
            .all()
        )

class ProductAuditHistoryView(ListAPIView):
    serializer_class = ProductAuditLogSerializer
    permission_classes = [IsAdminUser]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return ProductAuditLog.objects.none()

        return (
            ProductAuditLog.objects
            .filter(product_id=self.kwargs["pk"])
            .select_related("product", "actor")
            .order_by("-created_at", "-id")
        )


class UserRegistrationView(generics.CreateAPIView):
    serializer_class = UserRegistrationSerializer
    permission_classes = [permissions.AllowAny]
    throttle_classes = [RegistrationRateThrottle]


class SellerApplicationView(generics.CreateAPIView):
    serializer_class = SellerApplicationSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return SellerProfile.objects.filter(user=self.request.user)

    def perform_create(self, serializer):
        serializer.save()


class AdminSellerApplicationListView(generics.ListAPIView):
    serializer_class = SellerProfileAdminSerializer
    permission_classes = [permissions.IsAdminUser]

    def get_queryset(self):
        queryset = SellerProfile.objects.select_related("user")

        application_status = self.request.query_params.get("status")

        if application_status:
            queryset = queryset.filter(status=application_status.upper())

        return queryset


class AdminSellerApplicationReviewView(generics.UpdateAPIView):
    serializer_class = SellerProfileAdminSerializer
    permission_classes = [permissions.IsAdminUser]
    queryset = SellerProfile.objects.select_related("user")
    http_method_names = ["patch", "head", "options"]


class InventoryMovementCreateView(generics.CreateAPIView):
    queryset = InventoryMovement.objects.all()
    serializer_class = InventoryMovementSerializer
    permission_classes = [permissions.IsAdminUser]




class InventoryMovementListView(generics.ListAPIView):
    serializer_class = InventoryMovementSerializer
    permission_classes = [permissions.IsAdminUser]

    def get_queryset(self):
        queryset = InventoryMovement.objects.select_related(
            "product",
            "created_by",
        ).all()

        product_id = self.request.query_params.get("product_id")
        movement_type = self.request.query_params.get("movement_type")

        if product_id is not None:
            try:
                product_id = int(product_id)
            except (TypeError, ValueError):
                raise serializers.ValidationError({
                    "product_id": "Must be a valid integer."
                })

            if product_id < 1:
                raise serializers.ValidationError({
                    "product_id": "Must be greater than zero."
                })

            queryset = queryset.filter(product_id=product_id)

        if movement_type is not None:
            movement_type = movement_type.upper()

            allowed_types = [
                InventoryMovement.MovementType.STOCK_IN,
                InventoryMovement.MovementType.STOCK_OUT,
            ]

            if movement_type not in allowed_types:
                raise serializers.ValidationError({
                    "movement_type": "Must be IN or OUT."
                })

            queryset = queryset.filter(
                movement_type=movement_type
            )

        return queryset



@extend_schema(
    responses={200: OpenApiTypes.OBJECT},
)
@api_view(["GET"])
@permission_classes([IsAdminUser])
def inventory_summary(request):
    products = list(
        Product.objects.all().order_by("id")
    )

    movement_totals = (
        InventoryMovement.objects
        .values("product_id")
        .annotate(
            stock_in=Sum(
                "quantity",
                filter=Q(
                    movement_type=InventoryMovement.MovementType.STOCK_IN
                ),
            ),
            stock_out=Sum(
                "quantity",
                filter=Q(
                    movement_type=InventoryMovement.MovementType.STOCK_OUT
                ),
            ),
        )
    )

    totals_by_product = {
        item["product_id"]: item
        for item in movement_totals
    }

    results = []

    for product in products:
        totals = totals_by_product.get(product.id, {})

        results.append({
            "product_id": product.id,
            "product_name": product.name,
            "stock_in_total": totals.get("stock_in") or 0,
            "stock_out_total": totals.get("stock_out") or 0,
            "current_stock": product.stock_quantity,
        })

    return Response({
        "total_products": len(results),
        "inventory": results,
    })

@extend_schema(
    responses={200: OpenApiTypes.OBJECT},
)
@api_view(["GET"])
@permission_classes([IsAdminUser])
def low_stock_products(request):
    raw_threshold = request.query_params.get("threshold", "5")

    try:
        threshold = int(raw_threshold)
    except (TypeError, ValueError):
        raise ValidationError({
            "threshold": "Threshold must be a whole number."
        })

    if threshold < 0:
        raise ValidationError({
            "threshold": "Threshold cannot be negative."
        })

    products = Product.objects.filter(
        stock_quantity__lt=threshold
    ).order_by("stock_quantity", "name")

    results = [
        {
            "product_id": product.id,
            "product_name": product.name,
            "current_stock": product.stock_quantity,
            "threshold": threshold,
        }
        for product in products
    ]

    return Response({
        "threshold": threshold,
        "count": len(results),
        "low_stock_products": results,
    })



class CategoryListCreateView(generics.ListCreateAPIView):
    queryset = Category.objects.all()
    serializer_class = CategorySerializer
    permission_classes = [IsAdminOrReadOnly]



class SupplierListCreateView(generics.ListCreateAPIView):
    queryset = Supplier.objects.all()
    serializer_class = SupplierSerializer
    permission_classes = [IsAdminOrReadOnly]


class SupplierDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset = Supplier.objects.all()
    serializer_class = SupplierSerializer
    permission_classes = [IsAdminOrReadOnly]



class PurchaseOrderSummaryView(APIView):
    permission_classes = [IsAdminUser]

    @extend_schema(responses={200: OpenApiTypes.OBJECT})

    def get(self, request):
        # Calculate all status counts in a single database aggregation.
        summary = PurchaseOrder.objects.aggregate(
            total_orders=Count("id"),
            draft_orders=Count(
                "id",
                filter=Q(status=PurchaseOrder.Status.DRAFT),
            ),
            ordered_orders=Count(
                "id",
                filter=Q(status=PurchaseOrder.Status.ORDERED),
            ),
            received_orders=Count(
                "id",
                filter=Q(status=PurchaseOrder.Status.RECEIVED),
            ),
            cancelled_orders=Count(
                "id",
                filter=Q(status=PurchaseOrder.Status.CANCELLED),
            ),
        )

        # Calculate the value in the database while preserving decimal precision.
        total_value = PurchaseOrderItem.objects.aggregate(
            value=Sum(
                F("quantity") * F("unit_cost"),
                output_field=DecimalField(
                    max_digits=20,
                    decimal_places=2,
                ),
            )
        )["value"]

        if total_value is None:
            total_value = Decimal("0.00")

        summary["total_value"] = str(total_value)

        return Response(summary)
class PurchaseOrderListCreateView(generics.ListCreateAPIView):
    serializer_class = PurchaseOrderSerializer
    permission_classes = [permissions.IsAdminUser]
    ordering_fields = [
        "created_at",
        "updated_at",
        "order_number",
        "status",
    ]
    ordering = ["-created_at"]
    filter_backends = [OrderingFilter]

    def get_queryset(self):
        queryset = PurchaseOrder.objects.select_related(
            "supplier",
            "created_by",
        ).prefetch_related(
            "items__product"
        )

        params = self.request.query_params

        # Filter by purchase order status.
        order_status = params.get("status")
        if order_status:
            valid_statuses = PurchaseOrder.Status.values

            if order_status not in valid_statuses:
                from rest_framework.exceptions import ValidationError
                raise ValidationError({
                    "status": (
                        "Invalid purchase order status. "
                        f"Choose from: {', '.join(valid_statuses)}."
                    )
                })

            queryset = queryset.filter(status=order_status)


        # Filter by supplier ID.
        supplier_id = params.get("supplier")
        if supplier_id:
            if not supplier_id.isdigit():
                raise DRFValidationError({
                    "supplier": "Supplier must be a valid numeric ID."
                })

            supplier_id = int(supplier_id)

            if not Supplier.objects.filter(id=supplier_id).exists():
                raise DRFValidationError({
                    "supplier": "Supplier with this ID does not exist."
                })

            queryset = queryset.filter(supplier_id=supplier_id)

        # Filter by order number.
        order_number = params.get("order_number")
        if order_number:
            queryset = queryset.filter(
                order_number__icontains=order_number
            )


        # Filter by creation date.
        created_after = params.get("created_after")
        created_before = params.get("created_before")

        parsed_after = None
        parsed_before = None

        if created_after:
            try:
                parsed_after = parse_date(created_after)
            except ValueError:
                parsed_after = None

            if parsed_after is None:
                raise DRFValidationError({
                    "created_after": (
                        "Invalid date. Use YYYY-MM-DD format."
                    )
                })

        if created_before:
            try:
                parsed_before = parse_date(created_before)
            except ValueError:
                parsed_before = None

            if parsed_before is None:
                raise DRFValidationError({
                    "created_before": (
                        "Invalid date. Use YYYY-MM-DD format."
                    )
                })

        # Validate the date range before filtering.
        if (
            parsed_after is not None
            and parsed_before is not None
            and parsed_after > parsed_before
        ):
            raise DRFValidationError({
                "date_range": (
                    "'created_after' must be on or before "
                    "'created_before'."
                )
            })

        # Apply validated date filters.
        if parsed_after is not None:
            queryset = queryset.filter(
                created_at__date__gte=parsed_after
            )

        if parsed_before is not None:
            queryset = queryset.filter(
                created_at__date__lte=parsed_before
            )

        return queryset

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)


class PurchaseOrderDetailView(generics.RetrieveAPIView):
    queryset = PurchaseOrder.objects.select_related(
        "supplier",
        "created_by",
    ).prefetch_related(
        "items__product"
    )
    serializer_class = PurchaseOrderSerializer
    permission_classes = [permissions.IsAdminUser]


class PurchaseOrderMarkOrderedView(APIView):
    permission_classes = [permissions.IsAdminUser]

    @extend_schema(request=None, responses={200: OpenApiTypes.OBJECT})

    @transaction.atomic
    def post(self, request, pk):
        try:
            purchase_order = (
                PurchaseOrder.objects.select_for_update().get(pk=pk)
            )
        except PurchaseOrder.DoesNotExist:
            return Response(
                {"detail": "Purchase order not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        if purchase_order.status != PurchaseOrder.Status.DRAFT:
            return Response(
                {"detail": "Only draft orders can be marked as ordered."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not purchase_order.items.exists():
            return Response(
                {"detail": "Cannot order a purchase order with no items."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not purchase_order.supplier.is_active:
            return Response(
                {"detail": "Cannot order from an inactive supplier."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        purchase_order.status = PurchaseOrder.Status.ORDERED
        purchase_order.save(update_fields=["status", "updated_at"])

        return Response({
            "id": purchase_order.id,
            "order_number": purchase_order.order_number,
            "status": purchase_order.status,
            "message": "Purchase order marked as ordered.",
        })


class PurchaseOrderReceiveView(APIView):
    permission_classes = [permissions.IsAdminUser]

    @extend_schema(request=None, responses={200: OpenApiTypes.OBJECT})

    @transaction.atomic
    def post(self, request, pk):
        try:
            purchase_order = (
                PurchaseOrder.objects.select_for_update().get(pk=pk)
            )
        except PurchaseOrder.DoesNotExist:
            return Response(
                {"detail": "Purchase order not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        if purchase_order.status != PurchaseOrder.Status.ORDERED:
            return Response(
                {
                    "detail": (
                        "Only ordered purchase orders can be received. "
                        f"Current status: {purchase_order.status}."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        items = list(
            purchase_order.items.all().order_by("product_id")
        )

        if not items:
            return Response(
                {"detail": "Cannot receive an order with no items."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        for item in items:
            product = Product.objects.select_for_update().get(
                pk=item.product_id
            )

            product.stock_quantity += item.quantity
            product.save(
                update_fields=["stock_quantity", "updated_at"]
            )

            InventoryMovement.objects.create(
                product=product,
                movement_type=InventoryMovement.MovementType.STOCK_IN,
                quantity=item.quantity,
                note=f"Received against {purchase_order.order_number}",
                created_by=request.user,
            )

        purchase_order.status = PurchaseOrder.Status.RECEIVED
        purchase_order.received_at = timezone.now()
        purchase_order.save(
            update_fields=["status", "received_at", "updated_at"]
        )

        return Response({
            "id": purchase_order.id,
            "order_number": purchase_order.order_number,
            "status": purchase_order.status,
            "received_at": purchase_order.received_at,
            "message": "Purchase order received successfully.",
        })


class PurchaseOrderCancelView(APIView):
    permission_classes = [permissions.IsAdminUser]

    @extend_schema(request=None, responses={200: OpenApiTypes.OBJECT})

    @transaction.atomic
    def post(self, request, pk):
        try:
            purchase_order = (
                PurchaseOrder.objects
                .select_for_update()
                .get(pk=pk)
            )
        except PurchaseOrder.DoesNotExist:
            return Response(
                {"detail": "Purchase order not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        if purchase_order.status not in [
            PurchaseOrder.Status.DRAFT,
            PurchaseOrder.Status.ORDERED,
        ]:
            return Response(
                {
                    "detail": (
                        "Only draft or ordered purchase orders "
                        "can be cancelled. "
                        f"Current status: {purchase_order.status}."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        purchase_order.status = PurchaseOrder.Status.CANCELLED
        purchase_order.save(
            update_fields=["status", "updated_at"]
        )

        return Response(
            {
                "id": purchase_order.id,
                "order_number": purchase_order.order_number,
                "status": purchase_order.status,
                "message": "Purchase order cancelled successfully.",
            },
            status=status.HTTP_200_OK,
        )

class SellerDashboardView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(responses={200: OpenApiTypes.OBJECT})

    def get(self, request):
        user = request.user

        # Administrators use the global dashboard.
        if user.is_staff:
            return Response(
                {
                    "detail": (
                        "Administrators should use "
                        "/api/dashboard/summary/."
                    )
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        try:
            seller_profile = user.seller_profile
        except SellerProfile.DoesNotExist:
            return Response(
                {"detail": "You do not have a seller profile."},
                status=status.HTTP_403_FORBIDDEN,
            )

        if seller_profile.status != SellerProfile.Status.APPROVED:
            return Response(
                {
                    "detail": (
                        "An approved seller profile is required "
                        "to access this dashboard."
                    )
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        products = Product.objects.filter(owner=user)

        summary = products.aggregate(
            total=Count("id"),
            published=Count(
                "id",
                filter=Q(status=Product.Status.PUBLISHED),
            ),
            drafts=Count(
                "id",
                filter=Q(status=Product.Status.DRAFT),
            ),
            under_review=Count(
                "id",
                filter=Q(status=Product.Status.UNDER_REVIEW),
            ),
            total_units_in_stock=Sum("stock_quantity"),
        )

        low_stock_count = products.filter(
            stock_quantity__lt=5
        ).count()

        return Response(
            {
                "business_name": seller_profile.business_name,
                "products": {
                    "total": summary["total"],
                    "published": summary["published"],
                    "drafts": summary["drafts"],
                    "under_review": summary["under_review"],
                },
                "inventory": {
                    "total_units_in_stock": (
                        summary["total_units_in_stock"] or 0
                    ),
                    "low_stock_products": low_stock_count,
                    "low_stock_threshold": 5,
                },
            }
        )



class SellerDashboardSummaryView(APIView):
    permission_classes = [IsAdminUser]

    @extend_schema(responses={200: OpenApiTypes.OBJECT})

    def get(self, request):
        product_summary = Product.objects.aggregate(
            total=Count("id"),
            published=Count(
                "id",
                filter=Q(status=Product.Status.PUBLISHED),
            ),
            drafts=Count(
                "id",
                filter=Q(status=Product.Status.DRAFT),
            ),
            under_review=Count(
                "id",
                filter=Q(status=Product.Status.UNDER_REVIEW),
            ),
            total_units_in_stock=Sum("stock_quantity"),
        )

        low_stock_count = Product.objects.filter(
            stock_quantity__lt=5
        ).count()

        purchase_order_summary = PurchaseOrder.objects.aggregate(
            total=Count("id"),
            draft=Count(
                "id",
                filter=Q(status=PurchaseOrder.Status.DRAFT),
            ),
            ordered=Count(
                "id",
                filter=Q(status=PurchaseOrder.Status.ORDERED),
            ),
            received=Count(
                "id",
                filter=Q(status=PurchaseOrder.Status.RECEIVED),
            ),
            cancelled=Count(
                "id",
                filter=Q(status=PurchaseOrder.Status.CANCELLED),
            ),
        )

        recent_activity = (
            ProductAuditLog.objects
            .select_related("product", "actor")
            .order_by("-created_at", "-id")[:5]
        )

        recent_activity_data = ProductAuditLogSerializer(
            recent_activity,
            many=True,
        ).data

        return Response({
            "products": {
                "total": product_summary["total"],
                "published": product_summary["published"],
                "drafts": product_summary["drafts"],
                "under_review": product_summary["under_review"],
            },
            "inventory": {
                "total_units_in_stock": (
                    product_summary["total_units_in_stock"] or 0
                ),
                "low_stock_products": low_stock_count,
                "low_stock_threshold": 5,
            },
            "purchase_orders": purchase_order_summary,
            "recent_activity": recent_activity_data,
        })


class CustomerCartView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        responses={200: CartSerializer},
    )
    def get(self, request):
        cart, _ = Cart.objects.get_or_create(
            customer=request.user,
        )

        cart = Cart.objects.prefetch_related(
            "items__product",
        ).get(pk=cart.pk)

        return Response(
            CartSerializer(cart).data,
            status=status.HTTP_200_OK,
        )


class CustomerCartItemCreateView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=CartItemWriteSerializer,
        responses={201: CartItemSerializer},
    )
    def post(self, request):
        input_serializer = CartItemWriteSerializer(
            data=request.data,
        )
        input_serializer.is_valid(raise_exception=True)

        product_id = input_serializer.validated_data["product_id"]
        quantity = input_serializer.validated_data["quantity"]

        with transaction.atomic():
            cart, _ = Cart.objects.get_or_create(
                customer=request.user,
            )
            cart = Cart.objects.select_for_update().get(
                pk=cart.pk,
            )

            product = get_object_or_404(
                Product.objects.select_for_update(
                    of=("self",),
                ).select_related("owner"),
                pk=product_id,
            )

            if product.status != Product.Status.PUBLISHED:
                raise ValidationError(
                    {"product_id": "This product is not available for sale."}
                )

            if not product.owner_id:
                raise ValidationError(
                    {"product_id": "This product has no assigned seller."}
                )

            seller_profile = getattr(
                product.owner,
                "seller_profile",
                None,
            )

            if (
                seller_profile is None
                or seller_profile.status != SellerProfile.Status.APPROVED
            ):
                raise ValidationError(
                    {"product_id": "The product's seller is not approved."}
                )

            if product.price <= Decimal("0.00"):
                raise ValidationError(
                    {"product_id": "This product has an invalid price."}
                )

            cart_item = CartItem.objects.filter(
                cart=cart,
                product=product,
            ).first()

            new_quantity = quantity
            if cart_item:
                new_quantity += cart_item.quantity

            if new_quantity > product.stock_quantity:
                raise ValidationError(
                    {
                        "quantity": (
                            f"Only {product.stock_quantity} units are "
                            "currently in stock."
                        )
                    }
                )

            if cart_item:
                cart_item.quantity = new_quantity
                cart_item.save(update_fields=["quantity", "updated_at"])
            else:
                cart_item = CartItem.objects.create(
                    cart=cart,
                    product=product,
                    quantity=quantity,
                )

            cart.save(update_fields=["updated_at"])

        cart_item = CartItem.objects.select_related(
            "product",
        ).get(pk=cart_item.pk)

        return Response(
            CartItemSerializer(cart_item).data,
            status=status.HTTP_201_CREATED,
        )


class CustomerCartItemDetailView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=CartItemUpdateSerializer,
        responses={200: CartItemSerializer},
    )
    def patch(self, request, pk):
        input_serializer = CartItemUpdateSerializer(
            data=request.data,
        )
        input_serializer.is_valid(raise_exception=True)

        quantity = input_serializer.validated_data["quantity"]

        with transaction.atomic():
            cart_item = get_object_or_404(
                CartItem.objects.select_related("cart"),
                pk=pk,
                cart__customer=request.user,
            )

            cart = Cart.objects.select_for_update().get(
                pk=cart_item.cart_id,
            )

            product = Product.objects.select_for_update().filter(
                pk=cart_item.product_id,
            ).first()

            if product is None:
                raise ValidationError(
                    {"product": "This product is no longer available."}
                )

            if quantity > product.stock_quantity:
                raise ValidationError(
                    {
                        "quantity": (
                            f"Only {product.stock_quantity} units are "
                            "currently in stock."
                        )
                    }
                )

            cart_item.quantity = quantity
            cart_item.save(update_fields=["quantity", "updated_at"])
            cart.save(update_fields=["updated_at"])

        cart_item = CartItem.objects.select_related(
            "product",
        ).get(pk=cart_item.pk)

        return Response(
            CartItemSerializer(cart_item).data,
            status=status.HTTP_200_OK,
        )

    @extend_schema(
        responses={204: None},
    )
    def delete(self, request, pk):
        with transaction.atomic():
            cart_item = get_object_or_404(
                CartItem.objects.select_related("cart"),
                pk=pk,
                cart__customer=request.user,
            )

            cart = Cart.objects.select_for_update().get(
                pk=cart_item.cart_id,
            )

            cart_item.delete()
            cart.save(update_fields=["updated_at"])

        return Response(status=status.HTTP_204_NO_CONTENT)


class CustomerCartCheckoutView(APIView):
    permission_classes = [IsAuthenticated]
    serializer_class = CustomerCheckoutSerializer

    @extend_schema(
        request=CustomerCheckoutSerializer,
        responses={201: CustomerOrderSerializer},
    )
    def post(self, request):
        with transaction.atomic():
            cart, _ = Cart.objects.get_or_create(
                customer=request.user,
            )
            cart = Cart.objects.select_for_update().get(
                pk=cart.pk,
            )

            cart_items = list(
                cart.items.order_by("product_id"),
            )

            if not cart_items:
                raise ValidationError(
                    {"cart": "Your cart is empty."}
                )

            checkout_data = {
                "items": [
                    {
                        "product_id": item.product_id,
                        "quantity": item.quantity,
                    }
                    for item in cart_items
                ],
            }

            input_serializer = CustomerCheckoutSerializer(
                data=checkout_data,
                context={"request": request},
            )
            input_serializer.is_valid(raise_exception=True)
            order = input_serializer.save()

            cart.items.all().delete()

        return Response(
            CustomerOrderSerializer(order).data,
            status=status.HTTP_201_CREATED,
        )


class CustomerCheckoutView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=CustomerCheckoutSerializer,
        responses={201: CustomerOrderSerializer},
    )
    def post(self, request):
        serializer = CustomerCheckoutSerializer(
            data=request.data,
            context={"request": request},
        )
        serializer.is_valid(raise_exception=True)
        order = serializer.save()

        return Response(
            CustomerOrderSerializer(order).data,
            status=201,
        )


class CustomerOrderListView(ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = CustomerOrderSerializer

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return CustomerOrder.objects.none()

        return (
            CustomerOrder.objects
            .filter(customer=self.request.user)
            .prefetch_related("items__product")
            .order_by("-created_at", "-id")
        )


class CustomerOrderDetailView(RetrieveAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = CustomerOrderSerializer

    def get_queryset(self):
        return (
            CustomerOrder.objects
            .filter(customer=self.request.user)
            .prefetch_related("items__product")
        )


class CustomerOrderCancelView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=None,
        responses={200: CustomerOrderSerializer},
    )

    def post(self, request, pk):
        with transaction.atomic():
            try:
                order = (
                    CustomerOrder.objects
                    .select_for_update()
                    .get(pk=pk, customer=request.user)
                )
            except CustomerOrder.DoesNotExist:
                from rest_framework.exceptions import NotFound
                raise NotFound("Order not found.")

            items = list(
                CustomerOrderItem.objects
                .select_for_update()
                .filter(order=order)
                .order_by("id")
            )

            cancellable_statuses = {
                CustomerOrderItem.FulfillmentStatus.PENDING,
                CustomerOrderItem.FulfillmentStatus.CONFIRMED,
            }

            if not items:
                raise ValidationError(
                    "This order has no items to cancel."
                )

            if any(
                item.fulfillment_status not in cancellable_statuses
                for item in items
            ):
                raise ValidationError(
                    "This order cannot be cancelled because "
                    "one or more items have progressed beyond "
                    "the cancellable stage."
                )

            for item in items:
                product = (
                    Product.objects
                    .select_for_update()
                    .get(pk=item.product_id)
                )

                product.stock_quantity += item.quantity
                product.save(update_fields=["stock_quantity"])

                InventoryMovement.objects.create(
                    product=product,
                    movement_type=(
                        InventoryMovement.MovementType.STOCK_IN
                    ),
                    quantity=item.quantity,
                    created_by=request.user,
                    note=(
                        f"Customer cancelled order "
                        f"{order.order_number}, item {item.pk}"
                    )[:255],
                )

                item.fulfillment_status = (
                    CustomerOrderItem.FulfillmentStatus.CANCELLED
                )
                item.save(update_fields=["fulfillment_status"])

            order.status = CustomerOrder.Status.CANCELLED
            order.save(update_fields=["status", "updated_at"])

        order.refresh_from_db()

        return Response(
            CustomerOrderSerializer(order).data,
            status=status.HTTP_200_OK,
        )


class SellerOrderListView(ListAPIView):
    permission_classes = [IsApprovedSellerOrAdmin]
    serializer_class = SellerOrderItemSerializer

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return CustomerOrderItem.objects.none()

        return (
            CustomerOrderItem.objects
            .filter(seller=self.request.user)
            .select_related(
                "order",
                "order__customer",
                "product",
            )
            .order_by("-order__created_at", "-id")
        )

class SellerOrderDetailView(RetrieveAPIView):
    permission_classes = [IsApprovedSellerOrAdmin]
    serializer_class = SellerOrderItemSerializer

    def get_queryset(self):
        return (
            CustomerOrderItem.objects
            .filter(seller=self.request.user)
            .select_related(
                "order",
                "order__customer",
                "product",
            )
        )

class SellerOrderStatusUpdateView(APIView):
    permission_classes = [IsApprovedSellerOrAdmin]

    ALLOWED_TRANSITIONS = {
        CustomerOrderItem.FulfillmentStatus.PENDING: {
            CustomerOrderItem.FulfillmentStatus.CONFIRMED,
            CustomerOrderItem.FulfillmentStatus.CANCELLED,
        },
        CustomerOrderItem.FulfillmentStatus.CONFIRMED: {
            CustomerOrderItem.FulfillmentStatus.PROCESSING,
            CustomerOrderItem.FulfillmentStatus.CANCELLED,
        },
        CustomerOrderItem.FulfillmentStatus.PROCESSING: {
            CustomerOrderItem.FulfillmentStatus.SHIPPED,
            CustomerOrderItem.FulfillmentStatus.CANCELLED,
        },
        CustomerOrderItem.FulfillmentStatus.SHIPPED: {
            CustomerOrderItem.FulfillmentStatus.DELIVERED,
        },
        CustomerOrderItem.FulfillmentStatus.DELIVERED: set(),
        CustomerOrderItem.FulfillmentStatus.CANCELLED: set(),
    }

    @extend_schema(
        request=SellerOrderStatusUpdateSerializer,
        responses={200: SellerOrderItemSerializer},
    )


    def patch(self, request, pk):
        serializer = SellerOrderStatusUpdateSerializer(
            data=request.data
        )
        serializer.is_valid(raise_exception=True)
        new_status = serializer.validated_data["fulfillment_status"]

        with transaction.atomic():
            # Find the parent order ID without acquiring an item lock.
            # The parent order is always locked before its items.
            try:
                order_id = (
                    CustomerOrderItem.objects
                    .values_list("order_id", flat=True)
                    .get(pk=pk, seller=request.user)
                )
            except CustomerOrderItem.DoesNotExist:
                from rest_framework.exceptions import NotFound
                raise NotFound("Order item not found.")

            try:
                order = (
                    CustomerOrder.objects
                    .select_for_update()
                    .get(pk=order_id)
                )
            except CustomerOrder.DoesNotExist:
                from rest_framework.exceptions import NotFound
                raise NotFound("Order not found.")

            # Lock the order's items in a consistent order.
            locked_items = list(
                CustomerOrderItem.objects
                .select_for_update()
                .filter(order=order)
                .order_by("id")
            )

            item = next(
                (
                    order_item
                    for order_item in locked_items
                    if order_item.pk == pk
                    and order_item.seller_id == request.user.pk
                ),
                None,
            )

            if item is None:
                from rest_framework.exceptions import NotFound
                raise NotFound("Order item not found.")

            current_status = item.fulfillment_status

            if new_status not in self.ALLOWED_TRANSITIONS[current_status]:
                raise serializers.ValidationError({
                    "fulfillment_status": (
                        f"Cannot change status from {current_status} "
                        f"to {new_status}."
                    )
                })

            if new_status == CustomerOrderItem.FulfillmentStatus.CANCELLED:
                product = (
                    Product.objects
                    .select_for_update()
                    .get(pk=item.product_id)
                )

                product.stock_quantity += item.quantity
                product.save(update_fields=["stock_quantity"])

                InventoryMovement.objects.create(
                    product=product,
                    movement_type=(
                        InventoryMovement.MovementType.STOCK_IN
                    ),
                    quantity=item.quantity,
                    created_by=request.user,
                    note=(
                        f"Cancelled customer order "
                        f"{order.order_number}, item {item.pk}"
                    )[:255],
                )

            item.fulfillment_status = new_status
            item.save(update_fields=["fulfillment_status"])

            item_statuses = [
                order_item.fulfillment_status
                for order_item in locked_items
            ]

            active_statuses = [
                item_status
                for item_status in item_statuses
                if item_status
                != CustomerOrderItem.FulfillmentStatus.CANCELLED
            ]

            if not active_statuses:
                order.status = CustomerOrder.Status.CANCELLED
            elif all(
                item_status
                in {
                    CustomerOrderItem.FulfillmentStatus.DELIVERED,
                    CustomerOrderItem.FulfillmentStatus.CANCELLED,
                }
                for item_status in item_statuses
            ):
                order.status = CustomerOrder.Status.DELIVERED
            elif (
                CustomerOrderItem.FulfillmentStatus.PENDING
                in active_statuses
            ):
                order.status = CustomerOrder.Status.PENDING
            elif (
                CustomerOrderItem.FulfillmentStatus.CONFIRMED
                in active_statuses
            ):
                order.status = CustomerOrder.Status.CONFIRMED
            elif (
                CustomerOrderItem.FulfillmentStatus.PROCESSING
                in active_statuses
            ):
                order.status = CustomerOrder.Status.PROCESSING
            elif (
                CustomerOrderItem.FulfillmentStatus.SHIPPED
                in active_statuses
            ):
                order.status = CustomerOrder.Status.SHIPPED

            order.save(update_fields=["status", "updated_at"])

        item.refresh_from_db()

        return Response(
            SellerOrderItemSerializer(item).data,
            status=status.HTTP_200_OK,
        )
