import ComingSoon from "@/components/shared/ComingSoon";

export default function AIActivityPage() {
  return (
    <ComingSoon
      title="AI Activity"
      description="A feed of AI execution sessions: what the agent planned, what it asked, what it executed and what it verified. The control-plane tables in the ai schema already capture every step - a read-only API + this screen are part of the backend P2-P4 work."
    />
  );
}
