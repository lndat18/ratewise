"""Model dữ liệu của package email."""

from pydantic import BaseModel, ConfigDict


class FolderStatus(BaseModel):
    """Trạng thái UID của một folder IMAP ngay sau khi SELECT.

    Attributes:
        uidvalidity: UIDVALIDITY; đổi giá trị nghĩa là mọi UID cũ mất hiệu lực.
        uidnext: UID sẽ cấp cho mail kế tiếp trong folder.

    """

    model_config = ConfigDict(frozen=True)

    uidvalidity: int
    uidnext: int
