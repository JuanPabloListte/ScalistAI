"""Value objects de costos: `Money` y `Quantity`.

Inmutables (frozen) y validados en construcción. `Money` usa **Decimal, no
float**: es plata, y los redondeos de float acumulan error en presupuestos
grandes. La conversión desde/hacia el `float` de la DB (Material.unit_price)
ocurre en la capa anti-corrupción, no acá — el dominio siempre habla Decimal.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import Union

Numeric = Union[int, float, str, Decimal]

_CENTS = Decimal("0.01")


def _to_decimal(v: Numeric) -> Decimal:
    # str() evita el ruido binario de pasar un float directo a Decimal.
    return v if isinstance(v, Decimal) else Decimal(str(v))


@dataclass(frozen=True, slots=True)
class Money:
    """Monto monetario con su moneda. No se operan monedas distintas."""

    amount: Decimal
    currency: str = "ARS"

    def __post_init__(self) -> None:
        object.__setattr__(self, "amount", _to_decimal(self.amount))
        if not self.currency:
            raise ValueError("Money requiere una moneda")

    @classmethod
    def zero(cls, currency: str = "ARS") -> "Money":
        return cls(Decimal("0"), currency)

    def _same_currency(self, other: "Money") -> None:
        if self.currency != other.currency:
            raise ValueError(
                f"No se pueden operar monedas distintas: {self.currency} vs {other.currency}"
            )

    def __add__(self, other: "Money") -> "Money":
        self._same_currency(other)
        return Money(self.amount + other.amount, self.currency)

    def __sub__(self, other: "Money") -> "Money":
        self._same_currency(other)
        return Money(self.amount - other.amount, self.currency)

    def __mul__(self, factor: Numeric) -> "Money":
        return Money(self.amount * _to_decimal(factor), self.currency)

    def rounded(self) -> "Money":
        """Redondea a centavos (half-up) para presentación/persistencia."""
        return Money(self.amount.quantize(_CENTS, ROUND_HALF_UP), self.currency)

    def __str__(self) -> str:
        return f"{self.currency} {self.amount.quantize(_CENTS, ROUND_HALF_UP):,}"


@dataclass(frozen=True, slots=True)
class Quantity:
    """Cantidad física con su unidad (m2, ml, un, m3, kg, hs, bolsa, ...).
    Solo se suman cantidades de la misma unidad."""

    value: Decimal
    unit: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "value", _to_decimal(self.value))
        if not self.unit:
            raise ValueError("Quantity requiere una unidad")
        if self.value < 0:
            raise ValueError("Quantity no puede ser negativa")

    def __add__(self, other: "Quantity") -> "Quantity":
        if self.unit != other.unit:
            raise ValueError(f"Unidades distintas: {self.unit} vs {other.unit}")
        return Quantity(self.value + other.value, self.unit)

    def __mul__(self, factor: Numeric) -> "Quantity":
        return Quantity(self.value * _to_decimal(factor), self.unit)

    def __str__(self) -> str:
        return f"{self.value} {self.unit}"
