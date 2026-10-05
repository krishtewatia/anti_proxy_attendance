// MongoDB Initialization Script for Anti-Proxy Attendance Stack
// Creates the application database and an unprivileged application user.

const dbName = process.env.DATABASE_NAME || "anti_proxy_attendance";
const appUser = process.env.MONGO_APP_USERNAME || "antiproxy_user";
const appPassword = process.env.MONGO_APP_PASSWORD || "antiproxy_secure_password_replace_in_env";

const targetDb = db.getSiblingDB(dbName);

// Check if user already exists
const existingUsers = targetDb.getUsers().users.map(u => u.user);
if (!existingUsers.includes(appUser)) {
  targetDb.createUser({
    user: appUser,
    pwd: appPassword,
    roles: [
      { role: "readWrite", db: dbName }
    ]
  });
  print(`[INFO] Created application user '${appUser}' for database '${dbName}' with readWrite role.`);
} else {
  print(`[INFO] Application user '${appUser}' already exists on database '${dbName}'.`);
}
