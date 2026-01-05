import { useState } from "react";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import { FileText, Plus, Eye } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { toast } from "sonner";

interface Note {
  id: string;
  timestamp: string;
  symbol: string;
  title: string;
  body: string;
  tag: "plan" | "review" | "emotion" | "risk";
}

interface TraderNotesWidgetProps {
  defaultSymbol: string;
}

export function TraderNotesWidget({ defaultSymbol }: TraderNotesWidgetProps) {
  const [symbol, setSymbol] = useState(defaultSymbol);
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [tag, setTag] = useState<"plan" | "review" | "emotion" | "risk">("plan");
  const [selectedNote, setSelectedNote] = useState<Note | null>(null);

  // Mock notes
  const [notes] = useState<Note[]>([
    {
      id: "1",
      timestamp: new Date(Date.now() - 3600000).toLocaleString("en-US", { 
        month: "short", 
        day: "numeric", 
        hour: "2-digit", 
        minute: "2-digit" 
      }),
      symbol: "SPY",
      title: "Strong breakout above 430",
      body: "Price broke above 430 resistance with strong volume. VWAP holding as support. Plan to enter long on pullback to VWAP around 429.50. Target 433 with stop at 428.",
      tag: "plan",
    },
    {
      id: "2",
      timestamp: new Date(Date.now() - 7200000).toLocaleString("en-US", { 
        month: "short", 
        day: "numeric", 
        hour: "2-digit", 
        minute: "2-digit" 
      }),
      symbol: "QQQ",
      title: "Took profit too early",
      body: "Exited QQQ long at +$200 when it went on to run another $500. Need to work on letting winners run more. Was fear-based exit, not plan-based.",
      tag: "emotion",
    },
    {
      id: "3",
      timestamp: new Date(Date.now() - 10800000).toLocaleString("en-US", { 
        month: "short", 
        day: "numeric", 
        hour: "2-digit", 
        minute: "2-digit" 
      }),
      symbol: "SPY",
      title: "Position sizing decision",
      body: "Market volatility elevated (VIX > 18). Reducing position size by 50% to manage risk. ATR at 1.25 suggests wider stops needed.",
      tag: "risk",
    },
  ]);

  const handleAddNote = () => {
    if (!title.trim() || !body.trim()) {
      toast.error("Please fill in all fields");
      return;
    }

    toast.success("Note added successfully");
    // TODO: POST to /api/notes
    
    // Clear form
    setTitle("");
    setBody("");
    setTag("plan");
  };

  const getTagColor = (tag: string) => {
    const colors = {
      plan: "bg-primary/10 text-primary border-primary/30",
      review: "bg-info/10 text-info border-info/30",
      emotion: "bg-warning/10 text-warning border-warning/30",
      risk: "bg-destructive/10 text-destructive border-destructive/30",
    };
    return colors[tag as keyof typeof colors] || "bg-muted";
  };

  return (
    <>
      <Card className="p-5">
        <div className="space-y-4">
          {/* Header */}
          <div className="flex items-center gap-2 mb-1">
            <FileText className="h-4 w-4 text-muted-foreground" />
            <h3 className="text-sm font-semibold">Trader Notes</h3>
          </div>

          {/* Form */}
          <div className="space-y-3">
            <div className="grid grid-cols-2 gap-2">
              <div>
                <Label className="text-[10px] text-muted-foreground uppercase">Symbol</Label>
                <Select value={symbol} onValueChange={setSymbol}>
                  <SelectTrigger className="h-8 text-xs bg-background">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent className="bg-popover z-[100]">
                    <SelectItem value="SPY">SPY</SelectItem>
                    <SelectItem value="QQQ">QQQ</SelectItem>
                    <SelectItem value="IWM">IWM</SelectItem>
                    <SelectItem value="AAPL">AAPL</SelectItem>
                    <SelectItem value="TSLA">TSLA</SelectItem>
                  </SelectContent>
                </Select>
              </div>

              <div>
                <Label className="text-[10px] text-muted-foreground uppercase">Tag</Label>
                <Select value={tag} onValueChange={(v: any) => setTag(v)}>
                  <SelectTrigger className="h-8 text-xs bg-background">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent className="bg-popover z-[100]">
                    <SelectItem value="plan">Plan</SelectItem>
                    <SelectItem value="review">Review</SelectItem>
                    <SelectItem value="emotion">Emotion</SelectItem>
                    <SelectItem value="risk">Risk</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </div>

            <div>
              <Label className="text-[10px] text-muted-foreground uppercase">Title</Label>
              <Input
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                placeholder="Brief note title..."
                className="h-8 text-xs"
              />
            </div>

            <div>
              <Label className="text-[10px] text-muted-foreground uppercase">Note</Label>
              <Textarea
                value={body}
                onChange={(e) => setBody(e.target.value)}
                placeholder="Write your thoughts, plans, or observations..."
                className="text-xs min-h-[80px] resize-none"
              />
            </div>

            <Button onClick={handleAddNote} size="sm" className="w-full">
              <Plus className="h-3 w-3 mr-1" />
              Add Note
            </Button>
          </div>

          <Separator />

          {/* Notes List */}
          <div>
            <Label className="text-[10px] text-muted-foreground uppercase tracking-wide mb-2 block">
              Recent Notes ({notes.length})
            </Label>
            <ScrollArea className="h-[280px] pr-3">
              <div className="space-y-2">
                {notes.map((note) => (
                  <div
                    key={note.id}
                    className="border border-border rounded-md p-3 hover:bg-accent/5 transition-colors cursor-pointer"
                    onClick={() => setSelectedNote(note)}
                  >
                    <div className="flex items-start justify-between gap-2 mb-1.5">
                      <div className="flex items-center gap-2">
                        <Badge variant="outline" className="text-[10px] px-1.5 py-0">
                          {note.symbol}
                        </Badge>
                        <Badge className={`text-[10px] px-1.5 py-0 ${getTagColor(note.tag)}`}>
                          {note.tag}
                        </Badge>
                      </div>
                      <span className="text-[10px] text-muted-foreground whitespace-nowrap">
                        {note.timestamp}
                      </span>
                    </div>
                    <h4 className="text-xs font-semibold mb-1">{note.title}</h4>
                    <p className="text-xs text-muted-foreground line-clamp-2">
                      {note.body}
                    </p>
                  </div>
                ))}
              </div>
            </ScrollArea>
          </div>
        </div>
      </Card>

      {/* Note Detail Dialog */}
      <Dialog open={!!selectedNote} onOpenChange={() => setSelectedNote(null)}>
        <DialogContent className="max-w-lg">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <Badge variant="outline" className="text-xs">
                {selectedNote?.symbol}
              </Badge>
              <Badge className={`text-xs ${selectedNote && getTagColor(selectedNote.tag)}`}>
                {selectedNote?.tag}
              </Badge>
            </DialogTitle>
          </DialogHeader>

          {selectedNote && (
            <div className="space-y-4">
              <div>
                <Label className="text-xs text-muted-foreground">Time</Label>
                <div className="text-sm">{selectedNote.timestamp}</div>
              </div>

              <div>
                <Label className="text-xs text-muted-foreground">Title</Label>
                <div className="text-base font-semibold">{selectedNote.title}</div>
              </div>

              <div>
                <Label className="text-xs text-muted-foreground">Note</Label>
                <div className="text-sm leading-relaxed whitespace-pre-wrap bg-muted/30 rounded-md p-3">
                  {selectedNote.body}
                </div>
              </div>
            </div>
          )}
        </DialogContent>
      </Dialog>
    </>
  );
}
