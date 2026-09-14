from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    student_id: str = Field(alias="studentId")
    pin: str

    class Config:
        populate_by_name = True


class LoginResponse(BaseModel):
    token: str
    user: dict[str, Any]


class MemberRegistrationRequest(BaseModel):
    student_id: str = Field(alias="studentId")
    name: str
    pin: str

    class Config:
        populate_by_name = True


class PinSetupRequest(BaseModel):
    student_id: str = Field(alias="studentId")
    name: str
    pin: str

    class Config:
        populate_by_name = True


class MemberRegistrationReviewRequest(BaseModel):
    note: str | None = None
    grade: int
    part: str


class AttendanceConfirmRequest(BaseModel):
    event_id: int = Field(alias="eventId")

    class Config:
        populate_by_name = True


class AttendanceSubmitRequest(BaseModel):
    event_id: int = Field(alias="eventId")
    status: str
    reason: str | None = None

    class Config:
        populate_by_name = True


class LeaveRequestCreate(BaseModel):
    event_id: int = Field(alias="eventId")
    reason: str | None = None

    class Config:
        populate_by_name = True


class FeatureToggleRequest(BaseModel):
    enabled: bool


class ExternalSystemLinkRequest(BaseModel):
    name: str
    description: str
    url: str
    icon_url: str | None = Field(default=None, alias="iconUrl")

    class Config:
        populate_by_name = True


class AbsenceReportShareRequest(BaseModel):
    target_roles: list[str] = Field(alias="targetRoles")
    part: str | None = None
    start_date: str | None = Field(default=None, alias="startDate")
    end_date: str | None = Field(default=None, alias="endDate")

    class Config:
        populate_by_name = True


class EventUpsertRequest(BaseModel):
    date: str
    start_time: str | None = Field(default=None, alias="startTime")
    end_time: str | None = Field(default=None, alias="endTime")
    event_type: str = Field(alias="eventType")
    title: str
    location: str | None = None
    memo: str | None = None
    teacher_visit: bool = Field(default=False, alias="teacherVisit")

    class Config:
        populate_by_name = True


class BirthdayMessageRequest(BaseModel):
    recipient_id: int = Field(alias="recipientId")
    message: str

    class Config:
        populate_by_name = True


class ApprovalRequest(BaseModel):
    absence_type: str = Field(default="なし", alias="absenceType")

    class Config:
        populate_by_name = True


class MemberUpsertRequest(BaseModel):
    student_id: str = Field(alias="studentId")
    name: str
    grade: int = 1
    birthday: str | None = None
    part: str
    role: str = "一般部員"
    status: str = "在籍"
    email: str | None = None
    phone: str | None = None
    hometown: str | None = None
    band_years: int | None = Field(default=None, alias="bandYears")
    mbti: str | None = None
    class_late_weekdays: list[str] = Field(default_factory=list, alias="classLateWeekdays")
    duty: str | None = None
    join_date: str | None = Field(default=None, alias="joinDate")
    leave_date: str | None = Field(default=None, alias="leaveDate")

    class Config:
        populate_by_name = True


class TodoCreateRequest(BaseModel):
    scope: str = "全体"
    part: str | None = None
    category: str
    title: str
    detail: str | None = None


class PublicationCreateRequest(BaseModel):
    kind: str
    title: str
    period: str | None = None
    audience_type: str = Field(default="all", alias="audienceType")
    audience_value: str | None = Field(default=None, alias="audienceValue")
    member_id: int | None = Field(default=None, alias="memberId")

    class Config:
        populate_by_name = True


class AnnouncementCreateRequest(BaseModel):
    target_type: str = Field(alias="targetType")
    target_part: str | None = Field(default=None, alias="targetPart")
    target_grade: int | None = Field(default=None, alias="targetGrade")
    title: str
    message: str
    is_important: bool = Field(default=False, alias="isImportant")
    send_to_teacher: bool = Field(default=False, alias="sendToTeacher")

    class Config:
        populate_by_name = True


class PartMemoCreateRequest(BaseModel):
    part: str | None = None
    title: str
    memo: str


class PracticeReflectionRequest(BaseModel):
    target_scope: str = Field(alias="targetScope")
    title: str
    content: str

    class Config:
        populate_by_name = True


class ProfileUpdateRequest(BaseModel):
    birthday: str | None = None
    hometown: str | None = None
    band_years: int | None = Field(default=None, alias="bandYears")
    mbti: str | None = None
    class_late_weekdays: list[str] = Field(default_factory=list, alias="classLateWeekdays")
    duty: str | None = None

    class Config:
        populate_by_name = True
