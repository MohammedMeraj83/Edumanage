from app.blueprints.employees import make_employee_blueprint

bp = make_employee_blueprint("teachers", "/teachers", "teacher")
