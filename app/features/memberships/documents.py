import hashlib
import os
from io import BytesIO
from pathlib import Path, PurePosixPath
from uuid import uuid4
from xml.sax.saxutils import escape

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.features.memberships.models import MembershipDocument


def render_private_pdf(title: str, lines: list[str]) -> bytes:
    buffer = BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=18 * mm,
        leftMargin=18 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
        title=title,
    )
    styles = getSampleStyleSheet()
    story = [Paragraph(escape(title), styles["Title"]), Spacer(1, 8 * mm)]
    for line in lines:
        safe_line = escape(str(line)).replace("\n", "<br/>")
        story.append(Paragraph(safe_line, styles["BodyText"]))
        story.append(Spacer(1, 3 * mm))
    document.build(story)
    return buffer.getvalue()


def _document_root() -> Path:
    root = Path(settings.MEMBERSHIP_DOCUMENTS_DIR).expanduser().resolve()
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        os.chmod(root, 0o700)
    except OSError:
        pass
    return root


def private_document_path(storage_key: str) -> Path:
    relative = PurePosixPath(storage_key)
    if relative.is_absolute() or not relative.parts or any(part in {"", ".", ".."} for part in relative.parts):
        raise ValueError("Invalid private document storage key")
    root = _document_root()
    target = (root / Path(*relative.parts)).resolve()
    if not target.is_relative_to(root):
        raise ValueError("Invalid private document storage key")
    return target


async def create_private_pdf_document(
    db: AsyncSession,
    organization_id: int,
    subscription_id: int,
    document_type: str,
    title: str,
    lines: list[str],
    metadata: dict | None = None,
) -> MembershipDocument:
    content = render_private_pdf(title, lines)
    storage_key = (
        f"org-{organization_id}/subscriptions/{subscription_id}/"
        f"{document_type}-{uuid4().hex}.pdf"
    )
    target = private_document_path(storage_key)
    target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        os.chmod(target.parent, 0o700)
    except OSError:
        pass

    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(target, flags, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
    except Exception:
        try:
            target.unlink(missing_ok=True)
        finally:
            raise

    record = MembershipDocument(
        organization_id=organization_id,
        subscription_id=subscription_id,
        document_type=document_type,
        storage_key=storage_key,
        content_type="application/pdf",
        checksum=hashlib.sha256(content).hexdigest(),
        metadata_json=metadata or {},
    )
    db.add(record)
    return record
