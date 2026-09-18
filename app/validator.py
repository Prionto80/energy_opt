"""
Final plan validation / replay.

Re-checks the optimized plan against the original
request and directives, so the API never returns a
plan that violates any physical constraint or
operator directive.

Failures raise ValueError, which the API layer maps
to HTTP 422.
"""

from app.schemas import (
    OptimizeRequest,
    OptimizeResponse,
    Directive,
)


EPS = 0.01


def validate_plan(
    request: OptimizeRequest,
    directives: list[Directive],
    result: OptimizeResponse,
):

    # ========================================================
    # BASIC CHECK
    # ========================================================

    if len(result.hourly_plan) != 24:
        raise ValueError(
            "hourly_plan must contain exactly 24 entries"
        )

    if [item.hour for item in result.hourly_plan] != list(range(24)):
        raise ValueError("hourly_plan must be ordered from hour 0 through 23")

    solar_factor = [1.0] * 24
    for directive in directives:
        if directive.directive_type == "solar_reduction":
            for hour in directive.structured_adjustment["hours"]:
                solar_factor[hour] = min(
                    solar_factor[hour],
                    float(directive.structured_adjustment["factor"]),
                )

    previous_energy = (
        request.battery.initial_energy_kwh
    )

    # ========================================================
    # HOUR-BY-HOUR VALIDATION
    # ========================================================

    for plan in result.hourly_plan:

        hour = plan.hour
        input_hour = request.hours[hour]

        # NON-NEGATIVE VALUES
        if plan.grid_kwh < -EPS:
            raise ValueError(
                f"Negative grid value at hour {hour}"
            )

        if plan.solar_used_kwh < -EPS:
            raise ValueError(
                f"Negative solar value at hour {hour}"
            )

        if plan.battery_kwh < -EPS:
            raise ValueError(
                f"Negative battery value at hour {hour}"
            )

        # SOLAR LIMIT
        if (
            plan.solar_used_kwh
            > input_hour.solar_kwh * solar_factor[hour] + EPS
        ):
            raise ValueError(
                f"Solar usage exceeded at hour {hour}"
            )

        # ENERGY BALANCE
        # grid + solar + discharge = demand + charge
        left_side = (
            plan.grid_kwh
            + plan.solar_used_kwh
        )

        right_side = (
            input_hour.demand_kwh
        )

        if plan.battery_action == "discharge":
            left_side += plan.battery_kwh
        elif plan.battery_action == "charge":
            right_side += plan.battery_kwh
        elif plan.battery_action == "idle":
            if plan.battery_kwh > EPS:
                raise ValueError(f"Idle battery action must be zero at hour {hour}")
        else:
            raise ValueError(
                f"Invalid battery action at hour {hour}"
            )

        if abs(left_side - right_side) > EPS:
            raise ValueError(
                f"Energy balance failed at hour {hour}"
            )

        # BATTERY STATE TRANSITION
        if plan.battery_action == "charge":
            expected_energy = (
                previous_energy
                + plan.battery_kwh
            )
        elif plan.battery_action == "discharge":
            expected_energy = (
                previous_energy
                - plan.battery_kwh
            )
        else:
            expected_energy = previous_energy

        if abs(
            plan.battery_energy_after_kwh
            - expected_energy
        ) > EPS:
            raise ValueError(
                f"Battery state transition failed at hour {hour}"
            )

        # BATTERY CAPACITY
        if (
            plan.battery_energy_after_kwh
            < request.battery.minimum_energy_kwh - EPS
        ):
            raise ValueError(
                f"Battery minimum violated at hour {hour}"
            )

        if (
            plan.battery_energy_after_kwh
            > request.battery.capacity_kwh + EPS
        ):
            raise ValueError(
                f"Battery capacity violated at hour {hour}"
            )

        # CHARGE RATE
        if (
            plan.battery_action == "charge"
            and plan.battery_kwh
            > request.battery.max_charge_kwh_per_hour + EPS
        ):
            raise ValueError(
                f"Charge rate exceeded at hour {hour}"
            )

        # DISCHARGE RATE
        if (
            plan.battery_action == "discharge"
            and plan.battery_kwh
            > request.battery.max_discharge_kwh_per_hour + EPS
        ):
            raise ValueError(
                f"Discharge rate exceeded at hour {hour}"
            )

        previous_energy = (
            plan.battery_energy_after_kwh
        )

    # ========================================================
    # END-OF-DAY NEUTRALITY
    # ========================================================

    if abs(
        previous_energy
        - request.battery.initial_energy_kwh
    ) > EPS:
        raise ValueError(
            "End-of-day battery neutrality failed"
        )

    total_grid = sum(item.grid_kwh for item in result.hourly_plan)
    total_cost = sum(
        item.grid_kwh * request.hours[item.hour].tariff_bdt_per_kwh
        for item in result.hourly_plan
    )
    if abs(total_grid - result.total_grid_kwh) > EPS:
        raise ValueError("total_grid_kwh does not match hourly_plan")
    if abs(total_cost - result.total_cost_bdt) > EPS:
        raise ValueError("total_cost_bdt does not match hourly_plan")
    if abs(max(item.grid_kwh for item in result.hourly_plan) - result.peak_grid_kwh) > EPS:
        raise ValueError("peak_grid_kwh does not match hourly_plan")

    # ========================================================
    # RE-CHECK DIRECTIVES
    # ========================================================

    for directive in directives:

        adjustment = (
            directive.structured_adjustment
            or {}
        )

        hours = adjustment.get("hours", [])

        for hour in hours:

            plan = result.hourly_plan[hour]

            # NO CHARGE
            if (
                directive.directive_type
                == "no_charge_window"
            ):
                if (
                    plan.battery_action
                    == "charge"
                ):
                    raise ValueError(
                        f"Charging forbidden at hour {hour}"
                    )

            # NO DISCHARGE
            if (
                directive.directive_type
                == "no_discharge_window"
            ):
                if (
                    plan.battery_action
                    == "discharge"
                ):
                    raise ValueError(
                        f"Discharging forbidden at hour {hour}"
                    )

            # MINIMUM RESERVE
            if (
                directive.directive_type
                == "minimum_battery_reserve"
            ):
                required_reserve = float(
                    adjustment["minimum_energy_kwh"]
                )
                if (
                    plan.battery_energy_after_kwh
                    + EPS
                    < required_reserve
                ):
                    raise ValueError(
                        f"Battery reserve violated at hour {hour}"
                    )

            # MAX GRID
            if (
                directive.directive_type
                == "max_grid_window"
            ):
                max_grid = float(
                    adjustment["max_grid_kwh"]
                )
                if (
                    plan.grid_kwh
                    > max_grid + EPS
                ):
                    raise ValueError(
                        f"Grid cap violated at hour {hour}"
                    )
