/**
 * SOCIAL SHARE LOGIC
 * Portable module for handling share link generation.
 */

document.addEventListener('DOMContentLoaded', function () {
    const shareContainer = document.querySelector('.mm-tribute-share');
    if (!shareContainer) return;

    // The template might already have encoded links, 
    // but this JS can handle dynamic URL updating if needed.
    // For now, we ensure the buttons work correctly.

    const shareLinks = shareContainer.querySelectorAll('.mm-share-icon');

    shareLinks.forEach(link => {
        link.addEventListener('click', function (e) {
            // Special handling for Web Share API if supported and link is generic
            if (navigator.share && this.getAttribute('aria-label') === 'Share') {
                e.preventDefault();
                navigator.share({
                    title: document.title,
                    text: document.querySelector('meta[name="description"]')?.content || '',
                    url: window.location.href
                }).catch(err => {
                    console.log('Share failed:', err);
                });
            }
        });
    });
});
