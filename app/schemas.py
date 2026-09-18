"""
Request and response schemas for the GridWise
LLM Energy Optimizer API.

All energy units are kWh, tariff is BDT/kWh,
and hourly arrays must contain exactly 24 entries
indexed 0..23.
"""

from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)


# ============================================================
# BATTERY
# ============================================================

class Battery(StrictModel):
    """Battery configuration for the 24-hour horizon."""

    capacity_kwh: float = Field(
        ...,
        gt=0,
        description="Total battery capacity in kWh",
    )

    initial_energy_kwh: float = Field(
        ...,
        ge=0,
        description="Battery energy at hour 0",
    )

    minimum_energy_kwh: float = Field(
        ...,
        ge=0,
        description="Hard lower bound on battery energy",
    )

    max_charge_kwh_per_hour: float = Field(
        ...,
        gt=0,
        description="Maximum charge rate in kWh/hour",
    )

    max_discharge_kwh_per_hour: float = Field(
        ...,
        gt=0,
        description="Maximum discharge rate in kWh/hour",
    )

    @field_validator("minimum_energy_kwh")
    @classmethod
    def _reserve_not_above_capacity(cls, v, info):
        capacity = info.data.get("capacity_kwh")
        if capacity is not None and v > capacity:
            raise ValueError(
                "minimum_energy_kwh cannot exceed capacity_kwh"
            )
        return v

    @field_validator("initial_energy_kwh")
    @classmethod
    def _initial_within_bounds(cls, v, info):
        capacity = info.data.get("capacity_kwh")
        minimum = info.data.get("minimum_energy_kwh")
        if capacity is not None and v > capacity:
            raise ValueError(
                "initial_energy_kwh cannot exceed capacity_kwh"
            )
        if minimum is not None and v < minimum:
            raise ValueError(
                "initial_energy_kwh cannot be below "
                "minimum_energy_kwh"
            )
        return v


# ============================================================
# HOURLY DATA
# ============================================================

class HourData(StrictModel):
    """One hour of demand, solar availability, and tariff."""

    hour: int = Field(..., ge=0, le=23)
    demand_kwh: float = Field(..., ge=0)
    solar_kwh: float = Field(..., ge=0)
    tariff_bdt_per_kwh: float = Field(..., ge=0)


# ============================================================
# DIRECTIVE (LLM / interpreter output)
# ============================================================

class Directive(StrictModel):
    """
    Structured interpretation of a single operator note.

    The interpreter must emit exactly one Directive per
    operator note, with note_index matching the note's
    position in the request.
    """

    note_index: int = Field(..., ge=0)
    applies: bool
    directive_type: str
    structured_adjustment: Optional[dict] = None
    explanation: str = Field(..., min_length=1, max_length=500)


# ============================================================
# REQUEST
# ============================================================

class OptimizeRequest(StrictModel):
    """Top-level payload for POST /optimize-energy."""

    scenario_id: str = Field(..., min_length=1)
    operator_notes: List[str] = Field(
        ...,
        min_length=1,
        max_length=3,
        description="1 to 3 operator directives",
    )
    hours: List[HourData] = Field(
        ...,
        min_length=24,
        max_length=24,
        description="Exactly 24 hours of input data",
    )
    battery: Battery

    @field_validator("operator_notes")
    @classmethod
    def _notes_are_non_empty(cls, notes):
        if any(not note.strip() for note in notes):
            raise ValueError("operator_notes cannot contain empty strings")
        return notes

    @field_validator("hours")
    @classmethod
    def _hours_indexed_zero_to_twenty_three(cls, v):
        if len(v) != 24:
            raise ValueError("hours must contain exactly 24 entries")
        hours = [item.hour for item in v]
        if hours != list(range(24)):
            raise ValueError(
                "hours must be indexed 0..23 in ascending order"
            )
        return v


# ============================================================
# RESPONSE
# ============================================================

class HourPlan(StrictModel):
    """Optimized decision for a single hour."""

    hour: int = Field(..., ge=0, le=23)
    grid_kwh: float = Field(..., ge=0)
    solar_used_kwh: float = Field(..., ge=0)
    battery_action: str = Field(
        ...,
        description='"charge", "discharge", or "idle"',
    )
    battery_kwh: float = Field(..., ge=0)
    battery_energy_after_kwh: float = Field(..., ge=0)


class OptimizeResponse(StrictModel):
    """Top-level payload returned by POST /optimize-energy."""

    scenario_id: str
    directive_interpretation: List[Directive]
    hourly_plan: List[HourPlan] = Field(..., min_length=24, max_length=24)

    total_grid_kwh: float = Field(..., ge=0)
    total_cost_bdt: float = Field(..., ge=0)
    peak_grid_kwh: float = Field(..., ge=0)

    plan_summary: str
