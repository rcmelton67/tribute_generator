document.addEventListener("DOMContentLoaded", function () {
    const shareContainer = document.querySelector(".mm-tribute-share");
    if (!shareContainer) return;

    const pageUrl = window.location.href;
    const titleText = (document.querySelector(".mm-tribute-name")?.textContent || document.title || "").trim();
    const messageText = (document.querySelector(".mm-tribute-message")?.textContent || "").replace(/\s+/g, " ").trim();
    const imageEl = document.querySelector(".mm-tribute-image img");
    const imageUrl = imageEl?.getAttribute("src")
        ? new URL(imageEl.getAttribute("src"), window.location.href).href
        : "";

    const encodedUrl = encodeURIComponent(pageUrl);
    const encodedTitle = encodeURIComponent(titleText || "Memorial Tribute");
    const encodedMessage = encodeURIComponent(messageText || "Memorial tribute");
    const encodedImage = encodeURIComponent(imageUrl);

    const fbLink = shareContainer.querySelector('[data-platform="facebook"]');
    const pinLink = shareContainer.querySelector('[data-platform="pinterest"]');
    const emailLink = shareContainer.querySelector('[data-platform="email"]');

    if (fbLink) {
        fbLink.href = `https://www.facebook.com/sharer/sharer.php?u=${encodedUrl}`;
    }

    if (pinLink) {
        pinLink.href = imageUrl
            ? `https://pinterest.com/pin/create/button/?url=${encodedUrl}&media=${encodedImage}&description=${encodedMessage}`
            : `https://pinterest.com/pin/create/button/?url=${encodedUrl}&description=${encodedMessage}`;
    }

    if (emailLink) {
        const body = `I wanted to share this memorial tribute with you:\n\n${titleText}\n\n${pageUrl}`;
        emailLink.href = `mailto:?subject=${encodedTitle}&body=${encodeURIComponent(body)}`;
    }
});
