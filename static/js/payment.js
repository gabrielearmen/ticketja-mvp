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

    if (!copyButton || !codeField) {
        return;
    }

    const fallbackCopy = () => {
        codeField.focus();
        codeField.select();
        codeField.setSelectionRange(
            0,
            codeField.value.length
        );

        return document.execCommand("copy");
    };

    copyButton.addEventListener("click", async () => {
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
                : "Selecione e copie o código manualmente.";
        }

        if (copied) {
            const originalText = copyButton.textContent;

            copyButton.textContent = "Código copiado";

            window.setTimeout(() => {
                copyButton.textContent = originalText;
            }, 2500);
        }
    });
})();