(() => {
    "use strict";

    const timers = document.querySelectorAll(
        "[data-reservation-timer]"
    );

    timers.forEach((timer) => {
        const output = timer.querySelector(
            "[data-reservation-timer-output]"
        );

        const expiresAt = Date.parse(
            timer.dataset.expiresAt
        );

        if (!output || Number.isNaN(expiresAt)) {
            return;
        }

        let intervalId = null;

        const updateTimer = () => {
            const remainingMilliseconds =
                expiresAt - Date.now();

            if (remainingMilliseconds <= 0) {
                output.textContent = "00:00";
                timer.classList.add(
                    "reservation-timer--expired"
                );

                if (intervalId !== null) {
                    window.clearInterval(intervalId);
                }

                return;
            }

            const remainingSeconds = Math.ceil(
                remainingMilliseconds / 1000
            );

            const minutes = Math.floor(
                remainingSeconds / 60
            );

            const seconds = remainingSeconds % 60;

            output.textContent = [
                String(minutes).padStart(2, "0"),
                String(seconds).padStart(2, "0"),
            ].join(":");
        };

        updateTimer();

        intervalId = window.setInterval(
            updateTimer,
            1000
        );
    });
})();