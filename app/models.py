from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class Product(Base):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)

    cases: Mapped[list["TestCase"]] = relationship(back_populates="product")
    reports: Mapped[list["Report"]] = relationship(back_populates="product")


class TestCase(Base):
    __tablename__ = "test_cases"
    __table_args__ = (UniqueConstraint("product_id", "key", name="uq_case_product_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False, index=True)
    key: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    latest_version: Mapped[str] = mapped_column(String(32), default="v1.0.0")
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    product: Mapped[Product] = relationship(back_populates="cases")
    versions: Mapped[list["TestCaseVersion"]] = relationship(
        back_populates="case", cascade="all, delete-orphan", order_by="TestCaseVersion.created_at"
    )


class TestCaseVersion(Base):
    __tablename__ = "test_case_versions"
    __table_args__ = (UniqueConstraint("case_id", "version", name="uq_case_version"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("test_cases.id"), nullable=False, index=True)
    version: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[str] = mapped_column(String(500), default="")
    module: Mapped[str] = mapped_column(String(200), default="")
    priority: Mapped[str] = mapped_column(String(16), default="")
    client: Mapped[str] = mapped_column(String(32), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    preconditions: Mapped[str] = mapped_column(Text, default="")
    steps: Mapped[str] = mapped_column(Text, default="")
    expected: Mapped[str] = mapped_column(Text, default="")
    source_file: Mapped[str] = mapped_column(String(500), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    case: Mapped[TestCase] = relationship(back_populates="versions")


class Report(Base):
    __tablename__ = "reports"
    __table_args__ = (UniqueConstraint("product_id", "title", "type", name="uq_report_identity"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    latest_version: Mapped[str] = mapped_column(String(32), default="v1.0.0")

    product: Mapped[Product] = relationship(back_populates="reports")
    versions: Mapped[list["ReportVersion"]] = relationship(
        back_populates="report", cascade="all, delete-orphan", order_by="ReportVersion.created_at"
    )


class ReportVersion(Base):
    __tablename__ = "report_versions"
    __table_args__ = (UniqueConstraint("report_id", "version", name="uq_report_version"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    report_id: Mapped[int] = mapped_column(ForeignKey("reports.id"), nullable=False, index=True)
    version: Mapped[str] = mapped_column(String(32), nullable=False)
    summary: Mapped[str] = mapped_column(Text, default="")
    conclusion: Mapped[str] = mapped_column(Text, default="")
    source_file: Mapped[str] = mapped_column(String(500), default="")
    based_on_case_version: Mapped[str | None] = mapped_column(String(32), nullable=True, default=None)
    repo: Mapped[str] = mapped_column(String(1000), default="")
    branch: Mapped[str] = mapped_column(Text, default="")
    participants: Mapped[str] = mapped_column(Text, default="")
    style_css: Mapped[str] = mapped_column(Text, default="")
    header_parsed: Mapped[int] = mapped_column(Integer, default=0)
    details_parsed: Mapped[int] = mapped_column(Integer, default=0)
    source_size: Mapped[int] = mapped_column(Integer, default=0)
    source_mtime_ns: Mapped[int] = mapped_column(BigInteger, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    report: Mapped[Report] = relationship(back_populates="versions")
    links: Mapped[list["ReportCaseLink"]] = relationship(
        back_populates="report_version", cascade="all, delete-orphan"
    )


class ReportCaseLink(Base):
    __tablename__ = "report_case_links"
    __table_args__ = (
        UniqueConstraint("report_version_id", "case_id", name="uq_link_report_case"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    report_version_id: Mapped[int] = mapped_column(
        ForeignKey("report_versions.id"), nullable=False, index=True
    )
    case_id: Mapped[int] = mapped_column(ForeignKey("test_cases.id"), nullable=False, index=True)
    case_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("test_case_versions.id"), nullable=True
    )
    result: Mapped[str] = mapped_column(String(24), default="")
    heading: Mapped[str] = mapped_column(Text, default="")
    anchor: Mapped[str] = mapped_column(String(200), default="")
    section_html: Mapped[str] = mapped_column(Text, default="")
    fields_json: Mapped[str] = mapped_column(Text, default="[]")
    detail_text: Mapped[str] = mapped_column(Text, default="")
    detail_parsed: Mapped[int] = mapped_column(Integer, default=0)

    report_version: Mapped[ReportVersion] = relationship(back_populates="links")
    case: Mapped[TestCase] = relationship()
    case_version: Mapped[TestCaseVersion | None] = relationship()


class CaseDocMeta(Base):
    __tablename__ = "case_doc_metas"
    __table_args__ = (UniqueConstraint("product_id", "version", name="uq_case_doc_product_version"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False, index=True)
    version: Mapped[str] = mapped_column(String(32), nullable=False)
    source_file: Mapped[str] = mapped_column(String(500), default="")
    source_size: Mapped[int] = mapped_column(Integer, default=0)
    source_mtime_ns: Mapped[int] = mapped_column(BigInteger, default=0)
    pending_json: Mapped[str] = mapped_column(Text, default="[]")
    untested: Mapped[int] = mapped_column(Integer, default=0)
    info_available: Mapped[int] = mapped_column(Integer, default=0)
    info_title: Mapped[str] = mapped_column(String(500), default="")
    info_fields_json: Mapped[str] = mapped_column(Text, default="[]")
    info_fragment_page: Mapped[str] = mapped_column(Text, default="")
    parsed: Mapped[int] = mapped_column(Integer, default=0)


class CaseComment(Base):
    __tablename__ = "case_comments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("test_cases.id"), nullable=False, index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False, index=True)
    case_version: Mapped[str] = mapped_column(String(32), default="")
    body: Mapped[str] = mapped_column(Text, default="")
    images_json: Mapped[str] = mapped_column(Text, default="[]")
    environment: Mapped[str] = mapped_column(String(32), default="", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)

    case: Mapped[TestCase] = relationship()

class CaseReview(Base):
    __tablename__ = "case_reviews"
    __table_args__ = (
        UniqueConstraint("case_id", "endpoint", "version", name="uq_case_review_version"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("test_cases.id"), nullable=False, index=True)
    case_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("test_case_versions.id"), nullable=True, index=True
    )
    endpoint: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    version: Mapped[str] = mapped_column(String(32), nullable=False)
    result: Mapped[str] = mapped_column(String(24), default="")
    heading: Mapped[str] = mapped_column(Text, default="")
    fields_json: Mapped[str] = mapped_column(Text, default="[]")
    section_html: Mapped[str] = mapped_column(Text, default="")
    detail_text: Mapped[str] = mapped_column(Text, default="")
    repo: Mapped[str] = mapped_column(String(1000), default="")
    branch: Mapped[str] = mapped_column(Text, default="")
    participants: Mapped[str] = mapped_column(Text, default="")
    style_css: Mapped[str] = mapped_column(Text, default="")
    source_report_version_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    source_link_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    content_fingerprint: Mapped[str] = mapped_column(String(96), default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)

    case: Mapped[TestCase] = relationship()
    case_version: Mapped[TestCaseVersion | None] = relationship()

