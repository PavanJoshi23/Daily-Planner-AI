from client_agent import run_planner

if __name__ == "__main__":
    agenda = run_planner("Plan my day for today.")
    print("\n" + "=" * 60)
    print(agenda)