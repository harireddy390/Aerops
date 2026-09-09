function greet(user) {
  return user.profile ? "Hello, " + user.profile.name : "Hello, Guest";
}

module.exports = { greet };
