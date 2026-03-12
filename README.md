# Aeterna-Restaurants

This project now includes a simple SQLite-based user authentication system.

- A database file (`app.db`) is created automatically.
- The `users` table stores `id`, `username` (unique), `password_hash`, `salt`, `restaurant_name`, and `whatsapp_number`.
- Helper functions are available in `db_helper.py` (`signup_user`, `login_user`).

When you open the Streamlit app, a sidebar toggle allows visitors to sign up or log in. Access to the dashboard is gated by session state (`st.session_state['logged_in']`).

## User Settings

After logging in, a new **⚙️ Settings** option appears in the sidebar (for both admin and manager roles).  This screen lets the user view and edit their
restaurant name and WhatsApp number.  Changes are saved back to `app.db` and
immediately reflected in the dashboard titles and the WhatsApp QR link page.