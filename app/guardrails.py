"""
Deterministic validation of interpreter output.

The guardrail enforces structural invariants on every
Directive returned by the interpreter:

    * one directive per operator note
    * note_index matches position in the input list
    * directive_type is in the allow-list
    * structured_adjustment fields are well-typed and
      physically plausible (e.g. solar factor in [0,1],
      reserve <= capacity, max_grid non-negative).

Any failure raises ValueError, which the API layer
maps to HTTP 422.
"""

import math

from app.schemas import Directive


ALLOWED_DIRECTIVES = {
    "solar_reduction",
    "minimum_battery_reserve",
    "no_charge_window",
    "no_discharge_window",
    "max_grid_window",
    "no_op",
}


# ============================================================
# HOURS VALIDATION
# ============================================================

def validate_hours(hours):

    if not isinstance(hours, list):
        return False

    if len(hours) != len(set(hours)):
        return False

    if not all(
        isinstance(hour, int)
        for hour in hours
    ):
        return False

    if not all(
        0 <= hour <= 23
        for hour in hours
    ):
        return False

    if hours != sorted(hours):
        return False

    return True


# ============================================================
# MAIN VALIDATOR
# ============================================================

def validate_directives(
    directives: list[Directive],
    notes: list[str],
    capacity: float,
):

    # ----------------------------------------------------
    # ONE DIRECTIVE PER NOTE
    # ----------------------------------------------------

    if len(directives) != len(notes):
        raise ValueError(
            "Exactly one directive_interpretation entry "
            "is required per operator note"
        )

    for index, directive in enumerate(directives):

        # --------------------------------------------
        # NOTE INDEX ORDER
        # --------------------------------------------

        if directive.note_index != index:
            raise ValueError(
                "directive note_index order mismatch"
            )

        # --------------------------------------------
        # DIRECTIVE TYPE ALLOW-LIST
        # --------------------------------------------

        if (
            directive.directive_type
            not in ALLOWED_DIRECTIVES
        ):
            raise ValueError(
                "Unsupported directive type"
            )

        # --------------------------------------------
        # NO OP
        # --------------------------------------------

        if directive.directive_type == "no_op":

            if directive.applies:
                raise ValueError(
                    "no_op must have applies=false"
                )

            if (
                directive.structured_adjustment
                is not None
            ):
                raise ValueError(
                    "no_op must have null structured_adjustment"
                )

            continue

        # --------------------------------------------
        # NON NO-OP
        # --------------------------------------------

        if not directive.applies:
            raise ValueError(
                "Non-no_op directive must have applies=true"
            )

        adjustment = (
            directive.structured_adjustment
            or {}
        )

        if not validate_hours(adjustment.get("hours")):
            raise ValueError("Every non-no_op directive needs valid hours")

        # --------------------------------------------
        # SOLAR REDUCTION
        # --------------------------------------------

        if (
            directive.directive_type
            == "solar_reduction"
        ):

            if set(adjustment) != {"hours", "factor"}:
                raise ValueError("Invalid solar_reduction adjustment shape")

            factor = adjustment.get("factor")

            if not isinstance(
                factor,
                (int, float),
            ):
                raise ValueError(
                    "solar factor must be numeric"
                )

            if not math.isfinite(factor):
                raise ValueError(
                    "solar factor must be finite"
                )

            if not (0 <= factor <= 1):
                raise ValueError(
                    "solar factor must be between 0 and 1"
                )

        # --------------------------------------------
        # MINIMUM BATTERY RESERVE
        # --------------------------------------------

        elif (
            directive.directive_type
            == "minimum_battery_reserve"
        ):

            if set(adjustment) != {"hours", "minimum_energy_kwh"}:
                raise ValueError("Invalid minimum_battery_reserve adjustment shape")

            reserve = adjustment.get(
                "minimum_energy_kwh"
            )

            if not isinstance(
                reserve,
                (int, float),
            ):
                raise ValueError(
                    "minimum battery reserve must be numeric"
                )

            if not math.isfinite(reserve):
                raise ValueError(
                    "minimum battery reserve must be finite"
                )

            if reserve < 0:
                raise ValueError(
                    "minimum battery reserve cannot be negative"
                )

            if reserve > capacity:
                raise ValueError(
                    "minimum battery reserve cannot exceed capacity"
                )

        # --------------------------------------------
        # MAX GRID WINDOW
        # --------------------------------------------

        elif (
            directive.directive_type
            == "max_grid_window"
        ):

            if set(adjustment) != {"hours", "max_grid_kwh"}:
                raise ValueError("Invalid max_grid_window adjustment shape")

            max_grid = adjustment.get(
                "max_grid_kwh"
            )

            if not isinstance(
                max_grid,
                (int, float),
            ):
                raise ValueError(
                    "max_grid_kwh must be numeric"
                )

            if not math.isfinite(max_grid):
                raise ValueError(
                    "max_grid_kwh must be finite"
                )

            if max_grid < 0:
                raise ValueError(
                    "max_grid_kwh cannot be negative"
                )

        elif directive.directive_type in {
            "no_charge_window", "no_discharge_window"
        }:
            if set(adjustment) != {"hours"}:
                raise ValueError("Invalid battery-window adjustment shape")
