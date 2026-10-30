from drf_spectacular.utils import extend_schema
from rest_framework import generics, serializers, status
from rest_framework.response import Response

from core.api.exceptions import NotFoundError
from fusion_auth.permissions import HasModuleGrant, HasPermission
from modules.elm.api import serializers as s
from modules.elm.models import LeaveApplication
from modules.elm.selectors import balances as balance_selectors
from modules.elm.services import applications as application_service

MODULE = HasModuleGrant("elm")
P_APPLY = "elm.application.apply"
P_VIEW_SELF = "elm.application.view_self"
P_BALANCE_VIEW_SELF = "elm.balance.view_self"


def _actor(request):
    return getattr(request, "principal", None)


class ApplicationListCreateView(generics.GenericAPIView):
    """List the current employee's applications and create leave drafts."""

    serializer_class = s.LeaveApplicationSerializer

    def get_permissions(self):
        permission_code = (
            P_APPLY if self.request.method == "POST" else P_VIEW_SELF
        )
        permission_classes = [MODULE, HasPermission(permission_code)]
        return [permission() for permission in permission_classes]

    def get_queryset(self):
        actor = _actor(self.request)
        if actor is None or not getattr(actor, "user_id", None):
            return LeaveApplication.objects.none()

        return LeaveApplication.objects.filter(
            user_id=actor.user_id
        ).order_by("-created_at", "-pk")
    @extend_schema(operation_id="elm_application_list")
    def get(self, request, *args, **kwargs):
        data = self.get_serializer(self.get_queryset(), many=True).data
        return Response(data)

    def post(self, request, *args, **kwargs):
        payload = s.LeaveApplicationWriteSerializer(data=request.data)
        payload.is_valid(raise_exception=True)

        try:
            application = application_service.create_draft(
                actor=_actor(request),
                **payload.validated_data,
            )
        except application_service.InvalidLeaveApplicationError as exc:
            raise serializers.ValidationError(
                {"detail": str(exc)}
            ) from exc

        return Response(
            s.LeaveApplicationSerializer(application).data,
            status=status.HTTP_201_CREATED,
        )


class ApplicationDetailView(generics.GenericAPIView):
    """Retrieve an application belonging to the authenticated employee."""

    serializer_class = s.LeaveApplicationSerializer
    permission_classes = [MODULE, HasPermission(P_VIEW_SELF)]

    def get_queryset(self):
        actor = _actor(self.request)
        if actor is None or not getattr(actor, "user_id", None):
            return LeaveApplication.objects.none()

        return LeaveApplication.objects.filter(user_id=actor.user_id)
    @extend_schema(operation_id="elm_application_detail")
    def get(self, request, pk, *args, **kwargs):
        application = self.get_queryset().filter(pk=pk).first()
        if application is None:
            raise NotFoundError("Leave application not found.")

        return Response(self.get_serializer(application).data)


class ApplicationWithdrawView(generics.GenericAPIView):
    """Withdraw an employee's own draft application."""

    serializer_class = s.LeaveApplicationSerializer
    permission_classes = [MODULE, HasPermission(P_APPLY)]

    def post(self, request, pk, *args, **kwargs):
        try:
            application = application_service.withdraw_draft(
                actor=_actor(request),
                application_id=pk,
            )
        except application_service.InvalidLeaveApplicationError as exc:
            raise serializers.ValidationError(
                {"detail": str(exc)}
            ) from exc

        return Response(
            s.LeaveApplicationSerializer(application).data,
            status=status.HTTP_200_OK,
        )
class ApplicationPreflightView(generics.GenericAPIView):
    """Check whether an employee's draft can proceed to submission."""
    serializer_class = s.SubmissionPreflightSerializer
    permission_classes = [MODULE, HasPermission(P_APPLY)]

    def post(self, request, pk, *args, **kwargs):
        try:
            result = application_service.preflight_submission(
                actor=_actor(request),
                application_id=pk,
            )
        except application_service.InvalidLeaveApplicationError as exc:
            raise serializers.ValidationError(
                {"detail": str(exc)}
            ) from exc

        return Response(
            self.get_serializer(result).data,
            status=status.HTTP_200_OK,
        )
class LeaveBalanceListView(generics.GenericAPIView):
    """List the authenticated employee's leave balances."""

    serializer_class = s.LeaveBalanceSerializer
    permission_classes = [MODULE, HasPermission(P_BALANCE_VIEW_SELF)]

    def get(self, request, *args, **kwargs):
        actor = _actor(request)
        balances = balance_selectors.balances_for_employee(
            user_id=actor.user_id
        )
        return Response(self.get_serializer(balances, many=True).data)


class LeaveBalanceHistoryView(generics.GenericAPIView):
    """List the authenticated employee's balance transactions."""

    serializer_class = s.LeaveBalanceTransactionSerializer
    permission_classes = [MODULE, HasPermission(P_BALANCE_VIEW_SELF)]

    def get(self, request, *args, **kwargs):
        actor = _actor(request)
        transactions = balance_selectors.transactions_for_employee(
            user_id=actor.user_id
        )
        return Response(self.get_serializer(transactions, many=True).data)
