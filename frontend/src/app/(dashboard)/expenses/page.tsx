import { redirect } from "next/navigation";

// The Expense Entries module was an empty ComingSoon stub and is now
// REPLACED by Employees.  The route stays alive as a redirect so old links
// (AIActionCard record_expense tile, bookmarks) never 404.
export default function ExpensesPage() {
  redirect("/employees");
}
