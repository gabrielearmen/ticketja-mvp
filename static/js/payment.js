(() => {
    "use strict";

    const copyButton = document.querySelector(
        "[data-copy-pix]"
    );

    const codeField = document.querySelector(
        "[data-pix-code]"
    );

    const feedback = document.querySelector(
        "[data-copy-feedback]"
    );

    const paymentMonitor = document.querySelector(
        "[data-payment-monitor]"
    );

    const fallbackCopy = () => {
        if (!codeField) {
            return false;
        }

        codeField.focus();
        codeField.select();
        codeField.setSelectionRange(
            0,
            codeField.value.length
        );

        return document.execCommand("copy");
    };

    if (copyButton && codeField) {
        copyButton.addEventListener(
            "click",
            async () => {
                let copied = false;

                try {
                    if (
                        navigator.clipboard
                        && window.isSecureContext
                    ) {
                        await navigator.clipboard.writeText(
                            codeField.value
                        );

                        copied = true;
                    } else {
                        copied = fallbackCopy();
                    }
                } catch (error) {
                    copied = fallbackCopy();
                }

                if (feedback) {
                    feedback.textContent = copied
                        ? "Código PIX copiado."
                        : (
                            "Selecione e copie o código "
                            + "manualmente."
                        );
                }

                if (copied) {
                    const originalText = (
                        copyButton.textContent
                    );

                    copyButton.textContent = (
                        "Código copiado"
                    );

                    window.setTimeout(() => {
                        copyButton.textContent = (
                            originalText
                        );
                    }, 2500);
                }
            }
        );
    }

    if (!paymentMonitor) {
        return;
    }

    const currentState = (
        paymentMonitor.dataset.paymentState
    );

    const statusUrl = (
        paymentMonitor.dataset.paymentStatusUrl
    );

    if (
        !statusUrl
        || currentState !== "pending"
    ) {
        return;
    }

    let requestInProgress = false;
    let timerId = null;

    const scheduleNextCheck = (milliseconds = 5000) => {
        window.clearTimeout(timerId);

        timerId = window.setTimeout(
            checkPaymentStatus,
            milliseconds
        );
    };

    const checkPaymentStatus = async () => {
        if (requestInProgress) {
            scheduleNextCheck();
            return;
        }

        if (document.hidden) {
            scheduleNextCheck(10000);
            return;
        }

        requestInProgress = true;

        const controller = new AbortController();
        const abortTimer = window.setTimeout(
            () => controller.abort(),
            4000
        );

        try {
            const response = await fetch(
                statusUrl,
                {
                    method: "GET",
                    credentials: "same-origin",
                    headers: {
                        Accept: "application/json",
                    },
                    cache: "no-store",
                    signal: controller.signal,
                }
            );

            if (!response.ok) {
                scheduleNextCheck(10000);
                return;
            }

            const result = await response.json();

            if (
                result.state !== currentState
                || result.terminal
            ) {
                window.location.assign(
                    result.detail_url
                );
                return;
            }

            scheduleNextCheck();
        } catch (error) {
            scheduleNextCheck(10000);
        } finally {
            window.clearTimeout(abortTimer);
            requestInProgress = false;
        }
    };

    document.addEventListener(
        "visibilitychange",
        () => {
            if (!document.hidden) {
                scheduleNextCheck(250);
            }
        }
    );

    scheduleNextCheck();
})();