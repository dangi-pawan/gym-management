from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.common.responses.schemas import APIResponse


DurationUnit = Literal["day", "week", "month", "year"]
AccessType = Literal["home_gym", "all_gyms", "selected_gyms"]


class MembershipPlanRulesInput(BaseModel):
    freeze_allowed: bool = False
    max_freeze_days: int | None = Field(default=None, ge=1)
    transfer_allowed: Literal[False] = False
    cancellation_allowed: bool = True
    refund_allowed: bool = False
    auto_renew_allowed: bool = False

    @model_validator(mode="after")
    def validate_freeze_policy(self):
        if not self.freeze_allowed and self.max_freeze_days is not None:
            raise ValueError("max_freeze_days requires freeze_allowed=true")
        if self.freeze_allowed and self.max_freeze_days is None:
            raise ValueError("max_freeze_days is required when freezing is enabled")
        return self


class MembershipPlanCreate(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    description: str | None = Field(default=None, max_length=5000)
    duration_value: int = Field(gt=0, le=3650)
    duration_unit: DurationUnit
    base_price: Decimal = Field(ge=0, max_digits=12, decimal_places=2)
    joining_fee: Decimal = Field(default=Decimal("0.00"), ge=0, max_digits=12, decimal_places=2)
    currency: str = Field(default="INR", min_length=3, max_length=3, pattern="^[A-Z]{3}$")
    access_type: AccessType
    terms_id: int | None = Field(default=None, gt=0)
    rules: MembershipPlanRulesInput = Field(default_factory=MembershipPlanRulesInput)
    selected_gym_ids: list[int] = Field(default_factory=list)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Plan name cannot be empty")
        return value

    @field_validator("selected_gym_ids")
    @classmethod
    def unique_selected_gyms(cls, value: list[int]) -> list[int]:
        if any(gym_id <= 0 for gym_id in value):
            raise ValueError("Gym IDs must be positive")
        if len(value) != len(set(value)):
            raise ValueError("selected_gym_ids cannot contain duplicates")
        return value


class MembershipPlanUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=100)
    description: str | None = Field(default=None, max_length=5000)
    duration_value: int | None = Field(default=None, gt=0, le=3650)
    duration_unit: DurationUnit | None = None
    base_price: Decimal | None = Field(default=None, ge=0, max_digits=12, decimal_places=2)
    joining_fee: Decimal | None = Field(default=None, ge=0, max_digits=12, decimal_places=2)
    currency: str | None = Field(default=None, min_length=3, max_length=3, pattern="^[A-Z]{3}$")
    access_type: AccessType | None = None
    terms_id: int | None = Field(default=None, gt=0)
    rules: MembershipPlanRulesInput | None = None
    selected_gym_ids: list[int] | None = None

    @model_validator(mode="after")
    def reject_null_required_fields(self):
        required_when_set = (
            "name",
            "duration_value",
            "duration_unit",
            "base_price",
            "joining_fee",
            "currency",
            "access_type",
        )
        for field_name in required_when_set:
            if field_name in self.model_fields_set and getattr(self, field_name) is None:
                raise ValueError(f"{field_name} cannot be null")
        return self


class GymMembershipPlanUpdate(BaseModel):
    is_available: bool = True
    price_override: Decimal | None = Field(default=None, ge=0, max_digits=12, decimal_places=2)
    joining_fee_override: Decimal | None = Field(default=None, ge=0, max_digits=12, decimal_places=2)


class MembershipPlanResponse(BaseModel):
    id: int
    organization_id: int
    name: str
    description: str | None
    duration_value: int
    duration_unit: str
    base_price: Decimal
    joining_fee: Decimal
    currency: str
    access_type: str
    terms_id: int | None
    status: str
    selected_gym_ids: list[int] = Field(default_factory=list)
    rules: MembershipPlanRulesInput
    effective_price: Decimal | None = None
    effective_joining_fee: Decimal | None = None

    model_config = ConfigDict(from_attributes=True)


class MembershipTermsCreate(BaseModel):
    title: str = Field(min_length=3, max_length=150)
    content: str = Field(min_length=20, max_length=50000)

    @field_validator("title", "content")
    @classmethod
    def strip_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("This field cannot be empty")
        return value


class MembershipTermsResponse(BaseModel):
    id: int
    organization_id: int
    version: int
    title: str
    content: str
    content_hash: str
    status: str
    effective_from: datetime | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class MemberGymAssignmentCreate(BaseModel):
    gym_id: int = Field(gt=0)
    is_primary: bool = False


class MemberGymAssignmentResponse(BaseModel):
    id: int
    organization_id: int
    member_id: int
    gym_id: int
    is_primary: bool
    status: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class SubscriptionCreate(BaseModel):
    member_id: int = Field(gt=0)
    membership_plan_id: int = Field(gt=0)
    start_date: date
    terms_accepted: bool = False
    acceptance_method: Literal["staff_assisted"] = "staff_assisted"


class SubscriptionRenew(BaseModel):
    start_date: date | None = None
    terms_accepted: bool = False
    acceptance_method: Literal["member_portal", "staff_assisted"] = "staff_assisted"


class ManualPaymentCreate(BaseModel):
    payment_method: Literal["cash", "upi", "card", "bank_transfer", "other"]
    provider_reference: str | None = Field(default=None, max_length=150)


class SubscriptionResponse(BaseModel):
    id: int
    organization_id: int
    member_id: int
    membership_plan_id: int
    purchased_at_gym_id: int
    status: str
    start_date: date
    end_date: date
    plan_name_snapshot: str
    duration_value_snapshot: int
    duration_unit_snapshot: str
    plan_price_snapshot: Decimal
    joining_fee_snapshot: Decimal
    currency_snapshot: str
    access_type_snapshot: str
    created_at: datetime
    activated_at: datetime | None
    cancelled_at: datetime | None
    access_gym_ids: list[int] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class MembershipAccessResponse(BaseModel):
    member_id: int
    gym_id: int
    has_access: bool
    checked_on: date
    active_subscription_ids: list[int] = Field(default_factory=list)


class MembershipDocumentResponse(BaseModel):
    id: int
    subscription_id: int | None
    document_type: str
    content_type: str
    checksum: str
    generated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PaymentResponse(BaseModel):
    id: int
    subscription_id: int
    amount: Decimal
    currency: str
    payment_method: str
    provider: str
    provider_reference: str | None
    status: str
    paid_at: datetime | None

    model_config = ConfigDict(from_attributes=True)


class InvoiceResponse(BaseModel):
    id: int
    subscription_id: int
    invoice_number: str
    subtotal: Decimal
    tax_amount: Decimal
    gst_rate: Decimal
    cgst_amount: Decimal
    sgst_amount: Decimal
    igst_amount: Decimal
    gstin_snapshot: str | None
    tax_mode_snapshot: str
    total_amount: Decimal
    currency: str
    status: str
    issued_at: datetime | None

    model_config = ConfigDict(from_attributes=True)


MembershipPlanResponseEnvelope = APIResponse[MembershipPlanResponse]
MembershipPlanListEnvelope = APIResponse[list[MembershipPlanResponse]]
MembershipTermsEnvelope = APIResponse[MembershipTermsResponse]
MembershipTermsListEnvelope = APIResponse[list[MembershipTermsResponse]]
SubscriptionEnvelope = APIResponse[SubscriptionResponse]
SubscriptionListEnvelope = APIResponse[list[SubscriptionResponse]]
PaymentEnvelope = APIResponse[PaymentResponse]
InvoiceEnvelope = APIResponse[InvoiceResponse]
MembershipDocumentListEnvelope = APIResponse[list[MembershipDocumentResponse]]
MembershipAccessEnvelope = APIResponse[MembershipAccessResponse]


class RazorpayOrderCreate(BaseModel):
    pass


class MembershipTaxSettingsUpdate(BaseModel):
    gst_rate: Decimal = Field(ge=0, le=100, max_digits=5, decimal_places=2)
    gstin: str | None = Field(default=None, min_length=15, max_length=15, pattern=r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")
    tax_mode: Literal["intra_state", "inter_state"] = "intra_state"


class SubscriptionFreezeCreate(BaseModel):
    start_date: date
    end_date: date
    reason: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def validate_dates(self):
        if self.end_date <= self.start_date:
            raise ValueError("Freeze end_date must be after start_date")
        return self


class SubscriptionFreezeResponse(BaseModel):
    id: int
    organization_id: int
    subscription_id: int
    start_date: date
    end_date: date
    days: int
    status: str
    reason: str | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class RefundCreate(BaseModel):
    amount: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    reason: str | None = Field(default=None, max_length=500)


class RefundResponse(BaseModel):
    id: int
    payment_id: int
    amount: Decimal
    provider: str
    provider_refund_id: str | None
    status: str
    reason: str | None
    created_at: datetime
    processed_at: datetime | None

    model_config = ConfigDict(from_attributes=True)


class MembershipTaxSettingsResponse(BaseModel):
    gst_rate: Decimal
    gstin: str | None
    tax_mode: str

    model_config = ConfigDict(from_attributes=True)
