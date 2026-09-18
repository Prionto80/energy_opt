"""
Linear-programming optimizer for a 24-hour energy plan.

Variable layout (5 * 24 = 120 variables):

    [0 .. 24)              grid_kwh[t]
    [24 .. 48)             solar_used_kwh[t]
    [48 .. 72)             charge_kwh[t]
    [72 .. 96)             discharge_kwh[t]
    [96 .. 120)            battery_energy_after_kwh[t]

Objective:
    Minimize sum_t grid_kwh[t] * tariff_bdt_per_kwh[t]

Constraints:
    * energy balance every hour
    * battery state equation (E_t = E_{t-1} + charge - discharge)
    * end-of-day battery neutrality (E_23 == initial)
    * bounds on solar, charge rate, discharge rate, energy,
      and optional grid caps from directives
"""

import numpy as np

from scipy.optimize import linprog

from app.schemas import (
    OptimizeRequest,
    OptimizeResponse,
    Directive,
    HourPlan,
)


EPS = 1e-7


# ============================================================
# OPTIMIZER
# ============================================================

def optimize_energy(
    request: OptimizeRequest,
    directives: list[Directive],
) -> OptimizeResponse:

    HOURS = 24

    # --------------------------------------------------------
    # VARIABLE LAYOUT
    # --------------------------------------------------------

    TOTAL_VARIABLES = 5 * HOURS

    def variable_index(variable_type, hour):
        offsets = {
            "grid": 0,
            "solar": HOURS,
            "charge": 2 * HOURS,
            "discharge": 3 * HOURS,
            "energy": 4 * HOURS,
        }
        return offsets[variable_type] + hour

    # --------------------------------------------------------
    # OBJECTIVE
    # --------------------------------------------------------

    objective = np.zeros(TOTAL_VARIABLES)

    for hour in range(HOURS):
        objective[
            variable_index("grid", hour)
        ] = request.hours[hour].tariff_bdt_per_kwh

    # --------------------------------------------------------
    # DEFAULT BOUNDS
    # --------------------------------------------------------

    bounds = [
        (0, None)
        for _ in range(TOTAL_VARIABLES)
    ]

    # --------------------------------------------------------
    # DIRECTIVE EFFECTS
    # --------------------------------------------------------

    solar_factor = [1.0 for _ in range(HOURS)]

    minimum_reserve = [
        request.battery.minimum_energy_kwh
        for _ in range(HOURS)
    ]

    no_charge_hours: set[int] = set()
    no_discharge_hours: set[int] = set()

    grid_caps: dict[int, float] = {}

    # --------------------------------------------------------
    # APPLY DIRECTIVES
    # --------------------------------------------------------

    for directive in directives:

        adjustment = (
            directive.structured_adjustment
            or {}
        )

        hours = adjustment.get("hours", [])

        # SOLAR REDUCTION
        if (
            directive.directive_type
            == "solar_reduction"
        ):
            factor = float(adjustment["factor"])
            for hour in hours:
                solar_factor[hour] = min(
                    solar_factor[hour],
                    factor,
                )

        # BATTERY RESERVE
        elif (
            directive.directive_type
            == "minimum_battery_reserve"
        ):
            reserve = float(
                adjustment["minimum_energy_kwh"]
            )
            for hour in hours:
                minimum_reserve[hour] = max(
                    minimum_reserve[hour],
                    reserve,
                )

        # NO CHARGE
        elif (
            directive.directive_type
            == "no_charge_window"
        ):
            no_charge_hours.update(hours)

        # NO DISCHARGE
        elif (
            directive.directive_type
            == "no_discharge_window"
        ):
            no_discharge_hours.update(hours)

        # MAX GRID
        elif (
            directive.directive_type
            == "max_grid_window"
        ):
            max_grid = float(
                adjustment["max_grid_kwh"]
            )
            for hour in hours:
                if hour in grid_caps:
                    grid_caps[hour] = min(
                        grid_caps[hour],
                        max_grid,
                    )
                else:
                    grid_caps[hour] = max_grid

    # --------------------------------------------------------
    # SET VARIABLE BOUNDS
    # --------------------------------------------------------

    for hour in range(HOURS):

        # Solar
        solar_upper_bound = (
            request.hours[hour].solar_kwh
            * solar_factor[hour]
        )
        bounds[
            variable_index("solar", hour)
        ] = (0, solar_upper_bound)

        # Charge
        if hour in no_charge_hours:
            charge_upper_bound = 0
        else:
            charge_upper_bound = (
                request.battery
                .max_charge_kwh_per_hour
            )
        bounds[
            variable_index("charge", hour)
        ] = (0, charge_upper_bound)

        # Discharge
        if hour in no_discharge_hours:
            discharge_upper_bound = 0
        else:
            discharge_upper_bound = (
                request.battery
                .max_discharge_kwh_per_hour
            )
        bounds[
            variable_index("discharge", hour)
        ] = (0, discharge_upper_bound)

        # Battery energy
        bounds[
            variable_index("energy", hour)
        ] = (
            minimum_reserve[hour],
            request.battery.capacity_kwh,
        )

        # Grid cap
        if hour in grid_caps:
            bounds[
                variable_index("grid", hour)
            ] = (0, grid_caps[hour])

    # --------------------------------------------------------
    # EQUALITY CONSTRAINTS
    # --------------------------------------------------------

    A_eq = []
    b_eq = []

    for hour in range(HOURS):

        # ENERGY BALANCE
        row = np.zeros(TOTAL_VARIABLES)

        row[variable_index("grid", hour)] = 1
        row[variable_index("solar", hour)] = 1
        row[variable_index("discharge", hour)] = 1
        row[variable_index("charge", hour)] = -1

        A_eq.append(row)
        b_eq.append(
            request.hours[hour].demand_kwh
        )

        # BATTERY STATE
        battery_row = np.zeros(TOTAL_VARIABLES)

        battery_row[
            variable_index("energy", hour)
        ] = 1
        battery_row[
            variable_index("charge", hour)
        ] = -1
        battery_row[
            variable_index("discharge", hour)
        ] = 1

        if hour == 0:
            A_eq.append(battery_row)
            b_eq.append(
                request.battery.initial_energy_kwh
            )
        else:
            battery_row[
                variable_index("energy", hour - 1)
            ] = -1
            A_eq.append(battery_row)
            b_eq.append(0)

    # END-OF-DAY BATTERY NEUTRALITY
    final_energy_row = np.zeros(TOTAL_VARIABLES)
    final_energy_row[
        variable_index("energy", 23)
    ] = 1

    A_eq.append(final_energy_row)
    b_eq.append(
        request.battery.initial_energy_kwh
    )

    # --------------------------------------------------------
    # RUN LINEAR PROGRAM
    # --------------------------------------------------------

    result = linprog(
        objective,
        A_eq=np.array(A_eq),
        b_eq=np.array(b_eq),
        bounds=bounds,
        method="highs",
    )

    if not result.success:
        raise ValueError(
            "No feasible energy plan: "
            + result.message
        )

    solution = result.x

    # --------------------------------------------------------
    # BUILD HOURLY PLAN
    # --------------------------------------------------------

    hourly_plan = []

    for hour in range(HOURS):

        grid = max(
            0.0,
            solution[variable_index("grid", hour)],
        )

        solar = max(
            0.0,
            solution[variable_index("solar", hour)],
        )

        charge = max(
            0.0,
            solution[variable_index("charge", hour)],
        )

        discharge = max(
            0.0,
            solution[
                variable_index("discharge", hour)
            ],
        )

        battery_energy = solution[
            variable_index("energy", hour)
        ]

        if charge > EPS:
            action = "charge"
            battery_amount = charge
        elif discharge > EPS:
            action = "discharge"
            battery_amount = discharge
        else:
            action = "idle"
            battery_amount = 0.0

        hourly_plan.append(
            HourPlan(
                hour=hour,
                grid_kwh=round(grid, 6),
                solar_used_kwh=round(solar, 6),
                battery_action=action,
                battery_kwh=round(battery_amount, 6),
                battery_energy_after_kwh=round(
                    float(battery_energy), 6
                ),
            )
        )

    # --------------------------------------------------------
    # SUMMARY METRICS
    # --------------------------------------------------------

    total_grid = sum(
        item.grid_kwh
        for item in hourly_plan
    )

    total_cost = sum(
        item.grid_kwh
        * request.hours[item.hour].tariff_bdt_per_kwh
        for item in hourly_plan
    )

    peak_grid = max(
        item.grid_kwh
        for item in hourly_plan
    )

    # --------------------------------------------------------
    # FINAL RESPONSE
    # --------------------------------------------------------

    return OptimizeResponse(
        scenario_id=request.scenario_id,
        directive_interpretation=directives,
        hourly_plan=hourly_plan,
        total_grid_kwh=round(total_grid, 6),
        total_cost_bdt=round(total_cost, 6),
        peak_grid_kwh=round(peak_grid, 6),
        plan_summary=(
            "Optimized 24-hour plan with "
            f"total grid usage "
            f"{total_grid:.2f} kWh and "
            f"total cost "
            f"{total_cost:.2f} BDT."
        ),
    )
