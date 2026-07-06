document.addEventListener('DOMContentLoaded', () => {
    const tabButtons = document.querySelectorAll('.showcase-tab-btn');
    const slides = document.querySelectorAll('.showcase-slide');
    const details = document.querySelectorAll('.detail-content');
    const urlBar = document.getElementById('mockup-url');

    tabButtons.forEach(button => {
        button.addEventListener('click', () => {
            const targetTab = button.getAttribute('data-tab');

            // Deactivate all tabs
            tabButtons.forEach(btn => btn.classList.remove('active'));
            slides.forEach(slide => slide.classList.remove('active'));
            details.forEach(detail => detail.classList.remove('active'));

            // Activate clicked tab and matching slide/detail
            button.classList.add('active');
            
            const targetSlide = document.getElementById(`slide-${targetTab}`);
            if (targetSlide) targetSlide.classList.add('active');

            const targetDetail = document.getElementById(`detail-${targetTab}`);
            if (targetDetail) targetDetail.classList.add('active');

            // Update URL bar text to simulate routing
            if (urlBar) {
                urlBar.textContent = `localhost:5666/${targetTab}`;
            }
        });
    });
});
