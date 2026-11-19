from pydantic import BaseModel
import datetime


class ShipmentInfo(BaseModel):
    ship_date: str
    origin: str
    destination: str


class Location(BaseModel):
    country: str
    zip_code: str
    city: str | None
    state: str | None
    location_type: str


class Item(BaseModel):
    handling_unit: str
    units: int
    pieces: int | None
    length: float
    weight: float
    height: float
    freight_class: str
    mnfc: str | None
    description: str
    stackable: bool
    hazmat: bool

class Accessorials(BaseModel):
    pickup: list
    delivery: list


class Insurance(BaseModel):
    insured: bool
    declared_value: float | None


class QuoteRequest(BaseModel):
    shipment: str
    items: list
    accessorials: str
    insurance: str

